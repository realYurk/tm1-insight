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


def test_search_full_ancestor_paths(con):
    # Product 003 is a multi-parent leaf under Group 1 and Group 2.
    r = dimension_tree.search_elements(con, 'Tree', 'Product 003')
    m = r['matches'][0]
    assert m['name'] == 'Product 003'
    # Two distinct full ancestor lineages: Total > Brand A > Group 1 and Total > Brand B > Group 2
    paths = [tuple(p) for p in m['paths']]
    assert ('Total', 'Brand A', 'Group 1') in paths
    assert ('Total', 'Brand B', 'Group 2') in paths
    assert m['path_count'] == 2
    # parents field stays backward-compatible (direct parents only)
    assert set(m['parents']) == {'Group 1', 'Group 2'}


def test_search_multi_level_path(con):
    # Product 001 has a single lineage Total > Brand A > Group 1
    r = dimension_tree.search_elements(con, 'Tree', 'Product 001')
    m = r['matches'][0]
    assert m['paths'] == [['Total', 'Brand A', 'Group 1']]
    assert m['parents'] == ['Group 1']


def test_search_total_and_truncation(con):
    # Many matches beyond limit -> total reflects true count, returned is clipped.
    r = dimension_tree.search_elements(con, 'Tree', 'Product', limit=2)
    assert r['total'] == 4          # Product 001..004
    assert r['returned'] == 2       # limited
    assert r['truncated'] is True
    assert len(r['matches']) == 2


def test_search_cycle_does_not_loop(con):
    # Self-cycle on Total must not cause infinite ancestor path generation.
    con.execute('UPDATE dimensions SET edges=? WHERE name=?', [
        json.dumps([{'parent': 'Total', 'component': 'Total', 'weight': 1}]), 'Tree'])
    r = dimension_tree.search_elements(con, 'Tree', 'Total')
    assert r['total'] >= 1
    # Paths are bounded; the self-edge must not produce an unbounded chain.
    for m in r['matches']:
        for p in m['paths']:
            assert len(p) <= dimension_tree._MAX_SEARCH_DEPTH


def test_search_root_has_empty_path(con):
    # Top-level element (Total) has no ancestor path.
    r = dimension_tree.search_elements(con, 'Tree', 'Total')
    m = next(x for x in r['matches'] if x['name'] == 'Total')
    assert m['paths'] == []
    assert m['parents'] == []


def test_ancestor_paths_bounded_on_deep_chain(con):
    # A deep linear chain longer than MAX_SEARCH_DEPTH must not blow up.
    n = dimension_tree._MAX_SEARCH_DEPTH + 5
    elements = [{'name': 'N%d' % i, 'type': 'Consolidated' if i < n - 1 else 'Numeric'} for i in range(n)]
    edges = [{'parent': 'N%d' % i, 'component': 'N%d' % (i + 1), 'weight': 1} for i in range(n - 1)]
    con.execute('UPDATE dimensions SET elements=?, edges=? WHERE name=?', [
        json.dumps(elements), json.dumps(edges), 'Tree'])
    r = dimension_tree.search_elements(con, 'Tree', 'N%d' % (n - 1))
    assert r['total'] == 1
    m = r['matches'][0]
    # Path is truncated at MAX_SEARCH_DEPTH (cycle guard), never longer.
    assert all(len(p) <= dimension_tree._MAX_SEARCH_DEPTH for p in m['paths'])


def test_large_flat_dimension_roots(con):
    # A 10k-element flat dimension returns its roots bounded (default root_limit=200)
    # with the full count via root_total/root_truncated, so the front-end paginates
    # instead of rendering tens of thousands of DOM nodes at once. Search still
    # covers the full index.
    n = 10000
    elements = [{'name': 'E%05d' % i, 'type': 'Numeric'} for i in range(n)]
    con.execute('UPDATE dimensions SET elements=?, edges=? WHERE name=?', [
        json.dumps(elements), '[]', 'Tree'])
    s = dimension_tree.tree_summary(con, 'Tree')
    assert s['has_hierarchy'] is False
    assert len(s['roots']) == 200           # bounded page
    assert s['root_total'] == n             # full count
    assert s['root_truncated'] is True      # more available
    # Search still covers the full index (not just the first page).
    r = dimension_tree.search_elements(con, 'Tree', 'E09999')
    assert r['total'] == 1
    assert r['matches'][0]['name'] == 'E09999'
