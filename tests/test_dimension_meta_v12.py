"""Dimension Explorer v1.2：扩展元数据（dimension_metadata）与 TreeGrid 数据的合成测试。

不连接真实 TM1，全部用内存 DuckDB + 合成数据。覆盖：
1. dimension_meta 读扩展元数据（层级/子集定义/属性值）
2. tree_summary 合并扩展元数据（hierarchies/subset_definitions/attribute_values）
3. 元数据缺失时优雅降级（不伪造）
4. 超大维度（10万+）有界展示不受扩展元数据影响
"""
from __future__ import annotations

import json

import duckdb
import pytest

from tm1_insight.store import dimension_meta, dimension_tree
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    c = duckdb.connect()
    for ddl in ALL_TABLES.values():
        c.execute(ddl)
    yield c
    c.close()


def seed_basic(con, name="Tree"):
    elements = [{'name': 'Total', 'type': 'Consolidated'},
                {'name': 'A', 'type': 'Numeric'}, {'name': 'B', 'type': 'Numeric'}]
    edges = [{'parent': 'Total', 'component': 'A', 'weight': 1},
             {'parent': 'Total', 'component': 'B', 'weight': -1}]
    attributes = [{'name': 'Alias', 'type': 'Alias'}, {'name': 'Desc', 'type': 'String'}]
    subsets = [{'name': 'All', 'expression': None}]
    con.execute('INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)', [
        name, len(elements), json.dumps(elements), json.dumps(attributes),
        json.dumps(edges), json.dumps(subsets)])


def seed_metadata(con, name="Tree"):
    hierarchies = [{
        "name": "Tree", "dimension": "Tree", "element_count": 3,
        "edges": [{"parent": "Total", "component": "A", "weight": 1}],
        "default_member": "Total", "attributes": [{"name": "Alias", "type": "Alias"}],
        "subsets": ["All"], "status": "collected",
    }]
    subset_definitions = [
        {"name": "All", "hierarchy": "Tree", "dimension": "Tree",
         "type": "static", "expression": None, "elements": ["A", "B"], "status": "collected"},
    ]
    attribute_values = {
        "attributes": {
            "Alias": {"values": {"A": "Alpha", "B": "Beta"}, "status": "collected", "count": 2},
        }
    }
    con.execute('INSERT INTO dimension_metadata VALUES (?, ?, ?, ?, ?, ?)', [
        name, json.dumps(["Tree"]), json.dumps(hierarchies),
        json.dumps(subset_definitions), json.dumps(attribute_values), None])


def test_dimension_meta_reads_extension(con):
    seed_basic(con)
    seed_metadata(con)
    m = dimension_meta.metadata(con, "Tree")
    assert m is not None
    assert m["hierarchy_names"] == ["Tree"]
    assert m["hierarchies"][0]["element_count"] == 3
    assert m["subset_definitions"][0]["name"] == "All"
    assert m["subset_definitions"][0]["type"] == "static"
    assert m["attribute_values"]["attributes"]["Alias"]["values"]["A"] == "Alpha"


def test_dimension_meta_missing_returns_none(con):
    seed_basic(con)
    assert dimension_meta.metadata(con, "Tree") is None


def test_tree_summary_merges_extension(con):
    seed_basic(con)
    seed_metadata(con)
    s = dimension_tree.tree_summary(con, "Tree")
    assert s["hierarchies"][0]["name"] == "Tree"
    assert s["hierarchy_names"] == ["Tree"]
    assert s["subset_definitions"][0]["type"] == "static"
    assert s["attribute_values"]["attributes"]["Alias"]["values"]["B"] == "Beta"


def test_tree_summary_without_extension_degrades(con):
    seed_basic(con)
    s = dimension_tree.tree_summary(con, "Tree")
    # 未补采：扩展字段为空列表/空 dict，不伪造
    assert s["hierarchies"] == []
    assert s["subset_definitions"] == []
    assert s["attribute_values"] == {}


def test_tree_summary_large_dimension_bounded(con):
    # 10万+ 元素扁平维度，无层级，仍走有界预览
    n = 120000
    elements = [{'name': 'E%06d' % i, 'type': 'Numeric'} for i in range(n)]
    con.execute('INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)', [
        'Big', n, json.dumps(elements), '[]', '[]', '[]'])
    s = dimension_tree.tree_summary(con, "Big")
    assert s["large_dimension"] is True
    assert len(s["roots"]) <= 200
    assert s["root_total"] == n
    assert s["root_truncated"] is True


def test_subset_definitions_helper(con):
    seed_basic(con)
    seed_metadata(con)
    defs = dimension_meta.subset_definitions(con, "Tree")
    assert len(defs) == 1 and defs[0]["name"] == "All"


def test_attribute_values_helper(con):
    seed_basic(con)
    seed_metadata(con)
    av = dimension_meta.attribute_values(con, "Tree")
    assert av["attributes"]["Alias"]["count"] == 2
