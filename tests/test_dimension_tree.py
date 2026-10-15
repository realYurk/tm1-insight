"""Dimension hierarchy tree browsing: element tree, lazy children, search.

Covers the ARC-inspired browser scenarios on synthetic metadata, without live TM1.
"""
import json

import duckdb
import pytest

from tm1_insight.store import dimension_tree
from tm1_insight.store.schema import ALL_TABLES


def seed(con, name='Tree'):
    elements = [
        {'name': 'Total', 'type': 'Consolidated'},
        {'name': 'Brand A', 'type': 'Consolidated'},
        {'name': 'Brand B', 'type': 'Consolidated'},
        {'name': 'Group 1', 'type': 'Consolidated'},
        {'name': 'Product 001', 'type': 'Numeric'},
        {'name': 'Product 002', 'type': 'Numeric'},
        {'name': 'Product 003', 'type': 'Numeric'},
        {'name': 'Product 004', 'type': 'String'},
    ]
    # Multi-parent: Product 003 under both Group 1 and Group 2.
    edges = [
        {'parent': 'Total', 'component': 'Brand A', 'weight': 1},
        {'parent': 'Total', 'component': 'Brand B', 'weight': 1},
        {'parent': 'Brand A', 'component': 'Group 1', 'weight': 1},
        {'parent': 'Brand B', 'component': 'Group 2', 'weight': 1},
        {'parent': 'Group 1', 'component': 'Product 001', 'weight': 1},
        {'parent': 'Group 1', 'component': 'Product 002', 'weight': -1},
        {'parent': 'Group 1', 'component': 'Product 003', 'weight': 0},
        {'parent': 'Group 2', 'component': 'Product 003', 'weight': 1},
        {'parent': 'Group 2', 'component': 'Product 004', 'weight': 'runtime_weight'},
    ]
    attributes = [{'name': 'Alias', 'type': 'Alias'}, {'name': 'Desc', 'type': 'String'}]
    subsets = [{'name': 'Dynamic', 'expression': '{FILTER(...)}'}, {'name': None, 'expression': None}]
    con.execute('INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)', [
        name, len(elements), json.dumps(elements), json.dumps(attributes),
        json.dumps(edges), json.dumps(subsets)])


@pytest.fixture
def con():
    c = duckdb.connect()
    for ddl in ALL_TABLES.values():
        c.execute(ddl)
    seed(c)
    yield c
    c.close()


def test_tree_summary_roots_and_metadata(con):
    s = dimension_tree.tree_summary(con, 'Tree')
    assert s['name'] == 'Tree'
    assert s['recorded_elements'] == 8
    assert s['recorded_edges'] == 9
    assert s['has_hierarchy'] is True
    assert s['element_count'] == 8
    # Only top-level element is 'Total' (never a child).
    assert [r['name'] for r in s['roots']] == ['Total']
    assert s['roots'][0]['child_count'] == 2
    assert s['roots'][0]['has_children'] is True
    assert s['roots'][0]['type'] == 'Consolidated'
    assert len(s['attributes']) == 2 and s['attributes'][0]['name'] == 'Alias'
    assert len(s['subsets']) == 2


def test_children_lazy_load_with_weights(con):
    ch = dimension_tree.children(con, 'Tree', 'Total')
    assert [c['name'] for c in ch['children']] == ['Brand A', 'Brand B']
    ch = dimension_tree.children(con, 'Tree', 'Brand A')
    assert [c['name'] for c in ch['children']] == ['Group 1']
    ch = dimension_tree.children(con, 'Tree', 'Group 1')
    names = [c['name'] for c in ch['children']]
    assert names == ['Product 001', 'Product 002', 'Product 003']
    weights = {c['name']: c['weight'] for c in ch['children']}
    assert weights['Product 001'] == 1
    assert weights['Product 002'] == -1  # negative weight preserved
    assert weights['Product 003'] == 0   # zero weight preserved


def test_multi_parent_preserved(con):
    # Product 003 appears under both Group 1 and Group 2.
    g1 = dimension_tree.children(con, 'Tree', 'Group 1')
    g2 = dimension_tree.children(con, 'Tree', 'Group 2')
    assert 'Product 003' in [c['name'] for c in g1['children']]
    assert 'Product 003' in [c['name'] for c in g2['children']]
    search = dimension_tree.search_elements(con, 'Tree', 'Product 003')
    match = search['matches'][0]
    assert set(match['parents']) == {'Group 1', 'Group 2'}


def test_unknown_weight_not_fabricated(con):
    ch = dimension_tree.children(con, 'Tree', 'Group 2')
    prod4 = next(c for c in ch['children'] if c['name'] == 'Product 004')
    assert prod4['weight_known'] is False
    assert prod4['weight'] is None
    assert prod4['type'] == 'String'
    assert prod4['is_leaf'] is True


def test_search_across_dimension(con):
    r = dimension_tree.search_elements(con, 'Tree', 'Product')
    assert r['total'] == 4
    names = [m['name'] for m in r['matches']]
    assert 'Product 001' in names and 'Product 004' in names
    r = dimension_tree.search_elements(con, 'Tree', 'nothing-here')
    assert r['total'] == 0


def test_flat_dimension_no_hierarchy(con):
    con.execute('UPDATE dimensions SET edges=?, elements=? WHERE name=?', [
        '[]', json.dumps([{'name': 'A', 'type': 'Numeric'}, {'name': 'B', 'type': 'Numeric'}]), 'Tree'])
    s = dimension_tree.tree_summary(con, 'Tree')
    assert s['has_hierarchy'] is False
    assert sorted(r['name'] for r in s['roots']) == ['A', 'B']


def test_cycle_bounded_by_lazy_loading(con):
    # A cycle (self-edge) must not break summary/children; lazy loading never recurses.
    con.execute('UPDATE dimensions SET edges=? WHERE name=?', [
        json.dumps([{'parent': 'Total', 'component': 'Total', 'weight': 1}]), 'Tree'])
    s = dimension_tree.tree_summary(con, 'Tree')
    # Total is both parent and child of itself -> still returns a summary without infinite loop
    assert s['recorded_edges'] == 1
    ch = dimension_tree.children(con, 'Tree', 'Total')
    assert any(c['name'] == 'Total' for c in ch['children'])


def test_missing_dimension_returns_none(con):
    assert dimension_tree.tree_summary(con, 'DoesNotExist') is None
