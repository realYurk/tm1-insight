"""读取版本化扩展元数据（dimension_metadata 表）。

这是 Dimension Explorer v1.2 新增的「元数据覆盖层」，独立于既有 dimensions 表，
用于承载 P1 补采的完整层级 / 子集定义 / 属性值。缺失时优雅降级为 None，
绝不伪造未采集的元数据。

数据契约（对应 client.fetch_dimension_full 产出的扩展字段）：
- ``hierarchy_names``: list[str] —— 维度全部层级名
- ``hierarchies``: list[dict] —— 每层 {name, dimension, element_count, edges,
  default_member, attributes, subsets, status}
- ``subset_definitions``: list[dict] —— 每子集 {name, hierarchy, dimension,
  type(static/dynamic/unknown), expression, elements, status}
- ``attribute_values``: dict —— {attributes: {属性名: {values: {元素: 值}, status, count}}}
"""
from __future__ import annotations

import json


def _has_table(con, table: str) -> bool:
    available = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    return table in available


def _json_or_none(row_val):
    if row_val is None:
        return None
    try:
        return json.loads(row_val)
    except (ValueError, TypeError):
        return None


def metadata(con, name: str) -> dict | None:
    """返回某维度的扩展元数据；未采集或表不存在时返回 None。"""
    if not _has_table(con, "dimension_metadata"):
        return None
    row = con.execute(
        "SELECT hierarchy_names, hierarchies, subset_definitions, attribute_values, collected_at "
        "FROM dimension_metadata WHERE name = ?",
        [name],
    ).fetchone()
    if row is None:
        return None
    hierarchies = _json_or_none(row[1]) or []
    subset_definitions = _json_or_none(row[2]) or []
    attribute_values = _json_or_none(row[3]) or {}
    return {
        "name": name,
        "hierarchy_names": _json_or_none(row[0]) or [h.get("name") for h in hierarchies],
        "hierarchies": hierarchies,
        "subset_definitions": subset_definitions,
        "attribute_values": attribute_values,
        "collected_at": row[4],
    }


def hierarchies(con, name: str) -> list[dict]:
    """仅返回层级列表；未采集时返回空列表。"""
    m = metadata(con, name)
    return (m or {}).get("hierarchies", []) or []


def subset_definitions(con, name: str) -> list[dict]:
    """仅返回子集定义列表；未采集时返回空列表。"""
    m = metadata(con, name)
    return (m or {}).get("subset_definitions", []) or []


def attribute_values(con, name: str) -> dict:
    """仅返回属性值；未采集时返回空 dict。"""
    m = metadata(con, name)
    return (m or {}).get("attribute_values", {}) or {}
