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


def _name_expr() -> str:
    return (f"CASE WHEN entry.type = 'VARCHAR' THEN json_extract_string(entry.value, '$') "
            f"ELSE json_extract_string(entry.value, '$.name') END")


def _type_expr() -> str:
    return "json_extract_string(entry.value, '$.type')"


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


def tree_summary(con, name: str) -> dict:
    """Top-level summary for the dimension browser.

    Returns roots (top-level elements with no parent) plus metadata needed to
    render the page. Children are loaded lazily via :func:`children`.
    """
    meta = dimensions.metadata(con, name)
    if meta is None:
        return None
    elements = _elements_rows(con, name)
    edges = _edge_rows(con, name)

    # child_count per element (a consolidated element's direct children).
    child_counts: dict[str, int] = {}
    for edge in edges:
        parent = edge["parent"]
        if parent:
            child_counts[parent] = child_counts.get(parent, 0) + 1

    # parent names per child (for multi-parent detection and ancestor paths).
    parents_of: dict[str, list[str]] = {}
    for edge in edges:
        component = edge["component"]
        parent = edge["parent"]
        if component and parent:
            parents_of.setdefault(component, [])
            if parent not in parents_of[component]:
                parents_of[component].append(parent)

    # A top-level element is a named element that is never a child of anyone.
    children_seen = {c for c in parents_of}
    element_by_name: dict[str, dict] = {}
    for el in elements:
        nm = el["name"]
        if nm is not None:
            element_by_name[nm] = el

    roots = []
    for el in elements:
        nm = el["name"]
        if nm is None:
            continue
        etype = el["type"]
        is_leaf = _is_leaf(etype)
        child_count = child_counts.get(nm, 0)
        has_children = child_count > 0
        if nm in children_seen:
            continue  # has a parent, so not top-level
        roots.append({
            "name": nm,
            "type": etype,
            "is_leaf": is_leaf and not has_children,
            "child_count": child_count,
            "has_children": has_children,
            "parent_count": len(parents_of.get(nm, [])),
        })

    # If no edges at all, every element is a flat top-level member.
    has_hierarchy = len(edges) > 0

    # Attributes: only names + types are recorded; no attribute values.
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

    return {
        "name": name,
        "is_system": meta["is_system"],
        "element_count": meta["element_count"],
        "recorded_elements": len(elements),
        "recorded_edges": len(edges),
        "has_hierarchy": has_hierarchy,
        "roots": roots,
        "attributes": attributes,
        "subsets": subsets,
        "warnings": meta["warnings"],
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
    child_counts = {}
    count_rows = con.execute(
        "SELECT json_extract_string(entry.value, '$.parent') AS parent, count(*) AS n "
        "FROM json_each((SELECT " + _array('edges') + " FROM dimensions WHERE name = ?)) AS entry "
        "WHERE json_extract_string(entry.value, '$.parent') IS NOT NULL GROUP BY 1",
        [name],
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


def search_elements(con, name: str, keyword: str, limit: int = 100) -> dict:
    """Search across the whole dimension (not just the current page) and return
    each match with its ancestor path so the user can locate it in the tree."""
    kw = keyword.strip().lower()
    rows = con.execute(
        f"SELECT {_name_expr()} AS name, {_type_expr()} AS type "
        f"FROM json_each((SELECT {_array('elements')} FROM dimensions WHERE name = ?)) AS entry "
        f"WHERE lower(coalesce({_name_expr()}, '')) LIKE ? ORDER BY {_name_expr()} LIMIT ?",
        [name, f"%{kw}%", limit],
    ).fetchall()
    parents_of = {}
    edge_rows = con.execute(
        f"SELECT json_extract_string(entry.value, '$.component') AS component, "
        f"json_extract_string(entry.value, '$.parent') AS parent "
        f"FROM json_each((SELECT {_array('edges')} FROM dimensions WHERE name = ?)) AS entry",
        [name],
    ).fetchall()
    for component, parent in edge_rows:
        if component and parent:
            parents_of.setdefault(component, [])
            if parent not in parents_of[component]:
                parents_of[component].append(parent)
    matches = []
    for r in rows:
        nm = r[0]
        matches.append({
            "name": nm,
            "type": r[1],
            "parents": parents_of.get(nm, []),
        })
    return {"keyword": keyword, "matches": matches, "total": len(matches)}
