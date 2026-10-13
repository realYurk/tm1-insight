"""Read-only, bounded inspection of the dimension metadata actually stored.

No MDX evaluation, hierarchy inference, transitive weights or default edge weights.
JSON expansion/filtering stays in DuckDB; Python receives at most one page.
"""
from __future__ import annotations

import json
import math

FIELDS = ("elements", "edges", "attributes", "subsets")


def _array(column: str) -> str:
    return f"CASE WHEN json_type(try_cast({column} AS JSON)) = 'ARRAY' THEN {column} ELSE '[]' END"


def _string(path: str) -> str:
    return (f"CASE WHEN json_type(json_extract(entry.value, '{path}')) = 'VARCHAR' "
            f"THEN json_extract_string(entry.value, '{path}') END")


def _name() -> str:
    return f"CASE WHEN entry.type = 'VARCHAR' THEN json_extract_string(entry.value, '$') ELSE {_string('$.name')} END"


def _page(con, sql: str, params: list, page: int = 1, limit: int = 50) -> dict:
    limit = max(1, min(100, limit))
    total = con.execute(f"SELECT count(*) FROM ({sql}) AS counted", params).fetchone()[0]
    pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, pages))
    result = con.execute(sql + " LIMIT ? OFFSET ?", params + [limit, (page - 1) * limit])
    keys = [column[0] for column in result.description]
    return {"items": [dict(zip(keys, row)) for row in result.fetchall()], "total": total,
            "page": page, "pages": pages, "limit": limit,
            "start": (page - 1) * limit + 1 if total else 0, "end": min(page * limit, total)}


def search(con, keyword: str = "", page: int = 1) -> dict:
    return _page(con, """SELECT name, is_system, element_count FROM dimensions
        WHERE strpos(lower(name), lower(?)) > 0 ORDER BY name""", [keyword.strip()], page)


def metadata(con, name: str) -> dict | None:
    columns = ", ".join(f"json_type(try_cast({field} AS JSON)), json_array_length({_array(field)})"
                        for field in FIELDS)
    row = con.execute(f"SELECT name, is_system, element_count, {columns} FROM dimensions WHERE name = ?",
                      [name]).fetchone()
    if row is None:
        return None
    result = {"name": row[0], "is_system": row[1], "element_count": row[2], "fields": {}, "warnings": []}
    for index, field in enumerate(FIELDS):
        kind, count = row[3 + index * 2:5 + index * 2]
        result["fields"][field] = {"status": "recorded" if kind == "ARRAY" else "UNKNOWN", "count": count}
        if kind != "ARRAY":
            result["warnings"].append(f"{field} 未保存为有效数组，不能把未解析记录当作空结构。")
    if row[2] is not None and row[2] != result["fields"]["elements"]["count"]:
        result["warnings"].append("原记录元素数与已保存元素条目数不一致，请复查采集完整性。")
    return result


def record_sql(field: str) -> str:
    if field not in FIELDS:
        raise ValueError("Unknown dimension field")
    if field == "edges":
        columns = f"{_string('$.parent')} AS parent, {_string('$.component')} AS component, " \
                  "left(cast(json_extract(entry.value, '$.weight') AS VARCHAR), 240) AS weight, " \
                  "length(cast(json_extract(entry.value, '$.weight') AS VARCHAR)) AS weight_length"
    else:
        columns = f"{_name()} AS name"
        if field in {"elements", "attributes"}:
            columns += f", {_string('$.type')} AS recorded_type"
        if field == "subsets":
            expression = _string('$.expression')
            columns += f", left({expression}, 8000) AS expression, length({expression}) AS expression_length"
    return f"SELECT cast(entry.key AS BIGINT) AS position, {columns} FROM json_each((SELECT {_array(field)} FROM dimensions WHERE name = ?)) AS entry"


def decorate(items: list[dict], field: str, present: set[str] | None = None) -> None:
    for item in items:
        item["evidence"] = f"dimensions.{field}[{item['position']}]"
        if field == "edges":
            item["parent_exists"] = item["parent"] in (present or set())
            item["component_exists"] = item["component"] in (present or set())
            try:
                weight = json.loads(item["weight"]) if item["weight"] is not None else None
            except (ValueError, TypeError):
                weight = None
            item["weight_known"] = (item["weight_length"] is not None and item["weight_length"] <= 240
                                    and isinstance(weight, (int, float)) and not isinstance(weight, bool)
                                    and math.isfinite(weight))


def records(con, name: str, field: str, *, keyword: str = "", page: int = 1,
            element: str = "", index: int | None = None) -> dict:
    search_columns = "concat_ws(' ', parent, component)" if field == "edges" else "coalesce(name, '')"
    sql = f"WITH expanded AS ({record_sql(field)}) SELECT * FROM expanded WHERE strpos(lower({search_columns}), lower(?)) > 0"
    params = [name, keyword.strip()]
    if field == "edges" and element:
        sql += " AND (parent = ? OR component = ?)"; params.extend([element, element])
    if index is not None:
        sql += " AND position = ?"; params.append(index)
    sql += " ORDER BY position"
    result = _page(con, sql, params, page)
    if field == "edges" and result["items"]:
        # One existence query for this page's endpoints, never one scan per edge.
        names = sorted({value for item in result["items"] for value in (item["parent"], item["component"]) if value})
        present = set()
        if names:
            placeholders = ",".join("?" for _ in names)
            present = {r[0] for r in con.execute(f"""SELECT DISTINCT {_name()} AS name
                FROM json_each((SELECT {_array('elements')} FROM dimensions WHERE name = ?)) AS entry
                WHERE {_name()} IN ({placeholders})""", [name] + names).fetchall()}
        decorate(result["items"], field, present)
    else:
        decorate(result["items"], field)
    return result


def cubes(con, name: str, page: int = 1) -> dict:
    return _page(con, """SELECT rel.cube_name AS name, rel.dim_order,
        obj.name IS NOT NULL AS exists
        FROM cube_has_dimension rel LEFT JOIN cubes obj ON rel.cube_name = obj.name
        WHERE rel.dimension_name = ? ORDER BY rel.cube_name, rel.dim_order""", [name], page)
