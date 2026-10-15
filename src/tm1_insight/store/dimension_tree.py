"""Dimension hierarchy browsing: element tree with lazy child loading.

Read-only and bounded. Builds the parent/child tree from the recorded
``elements`` and ``edges`` JSON arrays without MDX evaluation, weight inference,
or fabrication of missing hierarchy data.

Data contract (matches the collector output and existing synthetic fixtures):
- ``elements``: list of ``{"name", "type"}`` entries; may also contain legacy
  strings, ``{}``, numbers or ``null`` (treated as name-less / UNKNOWN).
- ``edges``: list of ``{"parent", "component", "weight"}``; ``parent`` is the
  consolidated element, ``component`` the child, ``weight`` the raw weight
  (may be negative, zero, or a non-numeric string that stays unknown).

The tree preserves multi-parent relationships: a child that appears under
several parents is listed under each. Cycles are bounded by only ever
materialising one level at a time (lazy loading), so a corrupted self/cycle
edge can never recurse infinitely.
"""
from __future__ import annotations

import json
import math

from tm1_insight.store import dimensions


def _array(column: str) -> str:
    return f"CASE WHEN json_type(try_cast({column} AS JSON)) = 'ARRAY' THEN {column} ELSE '[]' END"


def _name_expr(alias: str = "entry") -> str:
    return (f"CASE WHEN {alias}.type = 'VARCHAR' THEN json_extract_string({alias}.value, '$') "
            f"ELSE json_extract_string({alias}.value, '$.name') END")


def _type_expr(alias: str = "entry") -> str:
    return f"json_extract_string({alias}.value, '$.type')"


def _known_weight(weight: str) -> str:
    # A weight is "known" only when it is a finite number that round-trips as JSON.
    return (f"CASE WHEN json_type({weight}) IN ('BIGINT','UBIGINT','INTEGER','DOUBLE','DECIMAL') "
            f"THEN cast({weight} AS VARCHAR) ELSE NULL END")


def _elements_rows(con, name: str) -> list[dict]:
    """All element rows (name + type) for one dimension. Bounded to element_count."""
    rows = con.execute(
        f"SELECT {_name_expr()} AS name, {_type_expr()} AS type "
        f"FROM json_each((SELECT {_array('elements')} FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    return [{"name": r[0], "type": r[1]} for r in rows]


def _edge_rows(con, name: str) -> list[dict]:
    weight_json = "json_extract(entry.value, '$.weight')"
    rows = con.execute(
        "SELECT json_extract_string(entry.value, '$.parent') AS parent, "
        "json_extract_string(entry.value, '$.component') AS component, "
        + _known_weight(weight_json) + " AS weight "
        "FROM json_each((SELECT " + _array('edges') + " FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    return [{"parent": r[0], "component": r[1], "weight": r[2]} for r in rows]


def _is_leaf(etype: str | None) -> bool:
    # Consolidated elements have children; Numeric/String/Alias/etc. are leaves.
    return (etype or "").strip().lower() not in ("consolidated",)


def tree_summary(con, name: str, root_limit: int = 200) -> dict:
    """Top-level summary for the dimension browser.

    Returns roots (top-level elements with no parent) plus metadata needed to
    render the page. Children are loaded lazily via :func:`children`.

    ``root_limit`` bounds how many roots are returned (large dimensions may have
    tens of thousands of top-level members); the full count is reported via
    ``root_total`` / ``root_truncated`` so the front-end can paginate.
    """
    meta = dimensions.metadata(con, name)
    if meta is None:
        return None

    # Very large dimensions (element_count above the index threshold) would force
    # a multi-10MB JSON parse per edge scan. Degrade to a bounded flat preview
    # instead: no hierarchy walk, just the first ``root_limit`` element names.
    # Search still covers the full index separately.
    from tm1_insight.store.dimension_index import THRESHOLD
    if meta["element_count"] is not None and meta["element_count"] > THRESHOLD:
        return _degraded_summary(con, name, meta, root_limit)

    # One-pass edge expansion via CTE: derive child_count, distinct child set,

    # and parent_count from a single json_each over the edges array, instead of
    # re-scanning the (potentially huge) edges array once per aggregation.
    edge_cte = ("WITH edges_cte AS ("
                "SELECT json_extract_string(entry.value, '$.parent') AS parent, "
                "json_extract_string(entry.value, '$.component') AS component "
                "FROM json_each((SELECT " + _array('edges') +
                " FROM dimensions WHERE name = ?)) AS entry)")

    # child_count: number of direct children per parent.
    child_count_rows = con.execute(
        edge_cte + " SELECT parent, count(*) AS n FROM edges_cte "
        "WHERE parent IS NOT NULL GROUP BY parent",
        [name],
    ).fetchall()
    child_counts = {r[0]: int(r[1]) for r in child_count_rows if r[0]}

    # Distinct child set (elements that have at least one parent) + parent_count.
    comp_rows = con.execute(
        edge_cte + " SELECT component, count(DISTINCT parent) AS pc FROM edges_cte "
        "WHERE component IS NOT NULL AND parent IS NOT NULL GROUP BY component",
        [name],
    ).fetchall()
    children_seen = {r[0] for r in comp_rows if r[0]}
    parent_count = {r[0]: int(r[1]) for r in comp_rows if r[0]}

    # Roots = named elements that are never a child. LEFT JOIN against the
    # distinct component set (hash join) avoids a huge NOT IN list.
    elem_src = "json_each((SELECT " + _array('elements') + " FROM dimensions WHERE name = ?)) AS el"
    name_expr = _name_expr("el")
    type_expr = _type_expr("el")
    comp_src = ("(SELECT DISTINCT json_extract_string(ed.value, '$.component') AS component "
                "FROM json_each((SELECT " + _array('edges') +
                " FROM dimensions WHERE name = ?)) AS ed "
                "WHERE json_extract_string(ed.value, '$.component') IS NOT NULL) AS comp")

    join_clause = ("FROM " + elem_src +
                   " LEFT JOIN " + comp_src + " ON " + name_expr + " = comp.component")
    root_filter = " WHERE " + name_expr + " IS NOT NULL AND comp.component IS NULL"

    root_total_row = con.execute(
        "SELECT count(*) " + join_clause + root_filter,
        [name, name],
    ).fetchone()
    root_total = int(root_total_row[0]) if root_total_row and root_total_row[0] is not None else 0

    root_rows = con.execute(
        "SELECT " + name_expr + " AS nm, " + type_expr + " AS tp " + join_clause +
        root_filter + " ORDER BY " + name_expr + " LIMIT ?",
        [name, name, root_limit],
    ).fetchall()

    roots = []
    for nm, etype in root_rows:
        if nm is None:
            continue
        is_leaf = _is_leaf(etype)
        child_count = child_counts.get(nm, 0)
        has_children = child_count > 0
        roots.append({
            "name": nm,
            "type": etype,
            "is_leaf": is_leaf and not has_children,
            "child_count": child_count,
            "has_children": has_children,
            "parent_count": parent_count.get(nm, 0),
        })

    # If no edges at all, every element is a flat top-level member.
    has_hierarchy = len(child_count_rows) > 0 or bool(children_seen)

    # Total recorded edge count (for transparency / diagnostics).
    edge_total_row = con.execute(
        "SELECT count(*) FROM json_each((SELECT " + _array('edges') + " FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchone()
    edge_total = int(edge_total_row[0]) if edge_total_row and edge_total_row[0] is not None else 0

    # Total recorded element count (name-carrying rows).
    elem_total_row = con.execute(
        "SELECT count(*) FROM " + elem_src + " WHERE " + name_expr + " IS NOT NULL",
        [name],
    ).fetchone()
    elem_total = int(elem_total_row[0]) if elem_total_row and elem_total_row[0] is not None else 0

    # Attributes: names + types recorded; attribute values are carried in the
    # optional versioned metadata layer (dimension_metadata), never fabricated here.
    attributes = []
    attr_rows = con.execute(
        f"SELECT {_name_expr()} AS name, {_type_expr()} AS type "
        f"FROM json_each((SELECT {_array('attributes')} FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    for r in attr_rows:
        attributes.append({"name": r[0], "type": r[1]})

    # Subsets: names and whether a real MDX expression is stored.
    subsets = []
    subset_rows = con.execute(
        f"SELECT {_name_expr()} AS name, json_extract_string(entry.value, '$.expression') AS expression "
        f"FROM json_each((SELECT {_array('subsets')} FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    for r in subset_rows:
        subsets.append({"name": r[0], "has_expression": bool(r[1])})

    # Versioned metadata overlay: hierarchies / subset definitions / attribute values
    # (dimension_metadata table). Absent when the dimension has not been incrementally
    # re-collected — the UI must render the "not collected" state, not fake data.
    meta_overlay = None
    try:
        from tm1_insight.store import dimension_meta
        meta_overlay = dimension_meta.metadata(con, name)
    except Exception:  # noqa: BLE001 —— 扩展表缺失时优雅降级
        meta_overlay = None

    return {
        "name": name,
        "is_system": meta["is_system"],
        "element_count": meta["element_count"],
        "recorded_elements": elem_total,
        "recorded_edges": edge_total,
        "has_hierarchy": has_hierarchy,
        "roots": roots,
        "root_total": root_total,
        "root_truncated": root_total > len(roots),
        "attributes": attributes,
        "subsets": subsets,
        "hierarchies": (meta_overlay or {}).get("hierarchies") or [],
        "hierarchy_names": (meta_overlay or {}).get("hierarchy_names") or [],
        "subset_definitions": (meta_overlay or {}).get("subset_definitions") or [],
        "attribute_values": (meta_overlay or {}).get("attribute_values") or {},
        "warnings": meta["warnings"],
    }


def _degraded_summary(con, name: str, meta: dict, root_limit: int) -> dict:
    """Bounded flat preview for very large dimensions (element_count > threshold).

    Avoids walking a multi-10MB edges JSON; returns only the first ``root_limit``
    element names as a flat list. Search still covers the full index separately.
    """
    name_expr = _name_expr("el")
    type_expr = _type_expr("el")
    elem_src = "json_each((SELECT " + _array('elements') + " FROM dimensions WHERE name = ?)) AS el"
    rows = con.execute(
        "SELECT " + name_expr + " AS nm, " + type_expr + " AS tp FROM " + elem_src +
        " WHERE " + name_expr + " IS NOT NULL ORDER BY " + name_expr + " LIMIT ?",
        [name, root_limit],
    ).fetchall()
    total_row = con.execute(
        "SELECT count(*) FROM " + elem_src + " WHERE " + name_expr + " IS NOT NULL",
        [name],
    ).fetchone()
    total = int(total_row[0]) if total_row and total_row[0] is not None else 0

    roots = []
    for nm, etype in rows:
        roots.append({
            "name": nm,
            "type": etype,
            "is_leaf": True,
            "child_count": 0,
            "has_children": False,
            "parent_count": 0,
        })

    return {
        "name": name,
        "is_system": meta["is_system"],
        "element_count": meta["element_count"],
        "recorded_elements": total,
        "recorded_edges": 0,
        "has_hierarchy": False,
        "roots": roots,
        "root_total": total,
        "root_truncated": total > len(roots),
        "large_dimension": True,
        "attributes": [],
        "subsets": [],
        "warnings": meta["warnings"] + ["维度规模过大，仅展示前 %d 个元素，请用搜索定位。" % root_limit],
    }


def children(con, name: str, element: str) -> dict:
    """Direct children of one element, with raw weight and child_count each."""
    # Direct edges where parent == element (component is the child).
    rows = con.execute(
        "SELECT json_extract_string(entry.value, '$.component') AS component, "
        + _known_weight("json_extract(entry.value, '$.weight')") + " AS weight "
        "FROM json_each((SELECT " + _array('edges') + " FROM dimensions WHERE name = ?)) AS entry "
        "WHERE json_extract_string(entry.value, '$.parent') = ? ORDER BY component",
        [name, element],
    ).fetchall()

    # element -> type lookup (only for the children we actually need).
    child_names = [r[0] for r in rows if r[0] is not None]
    type_of = {}
    if child_names:
        type_rows = con.execute(
            "SELECT " + _name_expr() + " AS name, " + _type_expr() + " AS type "
            "FROM json_each((SELECT " + _array('elements') + " FROM dimensions WHERE name = ?)) AS entry",
            [name],
        ).fetchall()
        for nm, etype in type_rows:
            if nm is not None:
                type_of[nm] = etype

    # child_count per name (how many direct children each child itself has).
    # Only resolve the child counts for the specific children we are returning,
    # so a large dimension does not force a full edge scan per expand.
    child_counts = {}
    if child_names:
        placeholders = ",".join("?" for _ in child_names)
        count_rows = con.execute(
            "SELECT json_extract_string(entry.value, '$.parent') AS parent, count(*) AS n "
            "FROM json_each((SELECT " + _array('edges') + " FROM dimensions WHERE name = ?)) AS entry "
            "WHERE json_extract_string(entry.value, '$.parent') IN (" + placeholders + ") GROUP BY 1",
            [name, *child_names],
        ).fetchall()
        for parent, n in count_rows:
            child_counts[parent] = n

    items = []
    for r in rows:
        child_name = r[0]
        weight_raw = r[1]
        etype = type_of.get(child_name)
        # known weight: a finite numeric value
        weight = None
        if weight_raw is not None:
            try:
                w = float(weight_raw)
                if math.isfinite(w):
                    weight = w
            except (ValueError, TypeError):
                weight = None
        cc = child_counts.get(child_name, 0)
        is_leaf = _is_leaf(etype)
        items.append({
            "name": child_name,
            "type": etype,
            "weight": weight,
            "weight_known": weight is not None,
            "child_count": cc,
            "has_children": cc > 0,
            "is_leaf": is_leaf and cc == 0,
        })
    return {"element": element, "children": items}


# Search result limits: bound path count, depth and matches so a large or
# cyclic dimension cannot blow up the response.
_MAX_SEARCH_PATHS = 8       # ancestor paths kept per matched element
_MAX_SEARCH_DEPTH = 32      # ancestor chain length cap (cycle guard)


def _ancestor_paths(edges: list[dict], parents_of: dict[str, list[str]]) -> dict[str, list[list[str]]]:
    """Map every element to its full ancestor paths.

    A path is a list of ancestor names from a top-level element down to the
    element's *direct* parent (the element itself is not included). Multi-parent
    elements yield one path per distinct ancestor lineage. Paths are bounded by
    ``_MAX_SEARCH_DEPTH`` (cycle guard) and ``_MAX_SEARCH_PATHS`` (explosion guard).
    """
    # Build reverse adjacency: parent -> [children].
    children_of: dict[str, list[str]] = {}
    for edge in edges:
        parent, component = edge["parent"], edge["component"]
        if not parent or not component:
            continue
        children_of.setdefault(parent, [])
        if component not in children_of[parent]:
            children_of[parent].append(component)

    # Top-level elements are parents that are never children themselves. A
    # child is any element that appears as a key in ``parents_of`` (i.e. it has
    # at least one parent). Roots are parents absent from that child set.
    has_parent = set(parents_of.keys())
    roots = [p for p in children_of if p not in has_parent]

    # Also include elements that appear in elements but are isolated (no edges).
    # Those get an empty path (top-level / no ancestor).
    paths_by_element: dict[str, list[list[str]]] = {}

    def walk(start: str) -> None:
        # Iterative DFS tracking the current ancestor chain.
        stack: list[tuple[str, list[str]]] = [(start, [])]
        seen_depth: dict[tuple[str, tuple[str, ...]], bool] = {}
        while stack:
            node, chain = stack.pop()
            if len(chain) >= _MAX_SEARCH_DEPTH:
                continue  # cycle / pathological depth guard
            for child in children_of.get(node, []):
                new_chain = chain + [node]
                key = (child, tuple(new_chain))
                if key in seen_depth:
                    continue  # avoid revisiting the same (child, path) — cycle guard
                seen_depth[key] = True
                paths_by_element.setdefault(child, [])
                if len(paths_by_element[child]) < _MAX_SEARCH_PATHS:
                    paths_by_element[child].append(new_chain)
                # Only recurse further if we still have path budget for descendants.
                stack.append((child, new_chain))

    for root in roots:
        walk(root)
    return paths_by_element


def search_elements(con, name: str, keyword: str, limit: int = 100) -> dict:
    """Search the whole dimension and return matches with full ancestor paths.

    Returns ``total`` (the true match count, independent of ``limit``),
    ``returned`` (how many matches are in this response) and ``truncated``
    (whether ``limit`` clipped the result). Each match carries ``paths`` — one
    ancestor chain per distinct lineage — plus a backwards-compatible
    ``parents`` field (the direct parents) for the existing UI.
    """
    kw = keyword.strip().lower()
    # True total count, before any LIMIT.
    total_row = con.execute(
        f"SELECT count(*) FROM json_each((SELECT {_array('elements')} FROM dimensions WHERE name = ?)) AS entry "
        f"WHERE lower(coalesce({_name_expr()}, '')) LIKE ?",
        [name, f"%{kw}%"],
    ).fetchone()
    total = int(total_row[0]) if total_row and total_row[0] is not None else 0

    rows = con.execute(
        f"SELECT {_name_expr()} AS name, {_type_expr()} AS type "
        f"FROM json_each((SELECT {_array('elements')} FROM dimensions WHERE name = ?)) AS entry "
        f"WHERE lower(coalesce({_name_expr()}, '')) LIKE ? ORDER BY {_name_expr()} LIMIT ?",
        [name, f"%{kw}%", limit],
    ).fetchall()

    # Very large dimensions: skip the full-graph ancestor walk (would parse a
    # multi-10MB edges JSON) and return matches without ancestor paths. The
    # match name still lets the user locate the element; the direct-parents
    # lookup is served by the indexed dimension pipeline for such dimensions.
    from tm1_insight.store.dimension_index import THRESHOLD
    meta = dimensions.metadata(con, name)
    large = bool(meta and meta["element_count"] is not None and meta["element_count"] > THRESHOLD)
    if large:
        matches = []
        for r in rows:
            matches.append({
                "name": r[0],
                "type": r[1],
                "parents": [],
                "paths": [],
                "path_count": 0,
            })
        return {
            "keyword": keyword,
            "matches": matches,
            "total": total,
            "returned": len(matches),
            "truncated": total > len(matches),
            "large_dimension": True,
        }

    # Load all edges once and build ancestor paths for the whole dimension.
    edge_rows = con.execute(
        f"SELECT json_extract_string(entry.value, '$.parent') AS parent, "
        f"json_extract_string(entry.value, '$.component') AS component "
        f"FROM json_each((SELECT {_array('edges')} FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    edges = [{"parent": r[0], "component": r[1]} for r in edge_rows]

    parents_of: dict[str, list[str]] = {}
    for edge in edges:
        parent, component = edge["parent"], edge["component"]
        if parent and component:
            parents_of.setdefault(component, [])
            if parent not in parents_of[component]:
                parents_of[component].append(parent)

    paths_by_element = _ancestor_paths(edges, parents_of)

    matches = []
    for r in rows:
        nm = r[0]
        parents = parents_of.get(nm, [])
        paths = paths_by_element.get(nm, [])
        matches.append({
            "name": nm,
            "type": r[1],
            "parents": parents,
            "paths": paths,
            "path_count": len(paths),
        })

    return {
        "keyword": keyword,
        "matches": matches,
        "total": total,
        "returned": len(matches),
        "truncated": total > len(matches),
    }
