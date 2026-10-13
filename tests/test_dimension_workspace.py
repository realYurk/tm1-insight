"""Dimension evidence inspection on synthetic metadata; no live TM1 requests."""
import hashlib
import json
import re

import duckdb
import pytest

from test_datasource_api import client  # noqa: F401
from tm1_insight.config import get_settings
from tm1_insight.store import dimensions
from tm1_insight.store.db import Store
from tm1_insight.store.schema import ALL_TABLES


def seed(con):
    elements = [{'name': 'Total', 'type': 'Consolidated'}, {'name': 'Income', 'type': 'Numeric'},
                {'name': 'Expense', 'type': 'Numeric'}, {'name': 'Disabled', 'type': 'Numeric'},
                'Legacy String', {'name': '<script>alert(1)</script>', 'type': 'String'}]
    edges = [dict(parent='Total', component='Income', weight=1),
             dict(parent='Total', component='Expense', weight=-1),
             dict(parent='Total', component='Disabled', weight=0),
             dict(parent='Total', component='Missing'),
             dict(parent='Income', component='Total', weight='runtime_weight'),
             dict(parent='Total', component='Income', weight=True), 7]
    subsets = [dict(name='Dynamic', expression="{FILTER({TM1SUBSETALL([Example])}, [Example].CURRENTMEMBER.NAME <> '')}"),
               dict(name='Static', expression=''), 'Name Only', dict(name='Invalid', expression=42)]
    con.execute('INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)', [
        'Example', len(elements), json.dumps(elements), json.dumps([dict(name='Code', type='String')]),
        json.dumps(edges), json.dumps(subsets)])
    con.execute("INSERT INTO cube_has_dimension VALUES ('MissingCube', 'Example', 0)")
    con.execute("INSERT INTO cubes (name) VALUES ('SyntheticCube')")
    con.execute("INSERT INTO cube_has_dimension VALUES ('SyntheticCube', 'Example', 2)")


@pytest.fixture
def con():
    con = duckdb.connect()
    for ddl in ALL_TABLES.values():
        con.execute(ddl)
    seed(con)
    yield con
    con.close()


def test_weights_original_positions_and_missing_endpoints(con):
    items = dimensions.records(con, 'Example', 'edges')['items']
    assert [item['weight'] for item in items[:4]] == ['1', '-1', '0', None]
    assert [item['weight_known'] for item in items] == [True, True, True, False, False, False, False]
    assert items[1]['evidence'] == 'dimensions.edges[1]'
    assert not items[3]['component_exists'] and items[3]['parent_exists']
    assert items[-1]['parent'] is None
    # Cycles stay direct records; they are never recursively expanded into value flow.
    adjacent = dimensions.records(con, 'Example', 'edges', element='Expense')
    assert adjacent['total'] == 1 and adjacent['items'][0]['weight'] == '-1'


def test_legacy_elements_and_subset_unknown(con):
    elements = dimensions.records(con, 'Example', 'elements')['items']
    assert elements[4]['name'] == 'Legacy String' and elements[4]['recorded_type'] is None
    for index, expression in [(1, ''), (2, None), (3, None)]:
        result = dimensions.records(con, 'Example', 'subsets', index=index)
        assert result['items'][0]['expression'] == expression
    result = dimensions.records(con, 'Example', 'subsets', index=0)
    assert 'TM1SUBSETALL' in result['items'][0]['expression']
    assert 'members' not in result['items'][0]
    assert dimensions.cubes(con, 'Example')['items'] == [
        dict(name='MissingCube', dim_order=0, exists=False), dict(name='SyntheticCube', dim_order=2, exists=True)]


def test_large_dimension_pagination_and_literal_search(con):
    # A lateral join can duplicate the entire JSON payload once per member.
    # This budget catches that failure even when only 50 rows reach Python.
    con.execute("SET memory_limit='256MB'")
    con.execute("SET threads=2")
    values = [{'name': f'Element {index:05}', 'type': 'Numeric'} for index in range(10003)]
    values[-1]['name'] = 'Last_%_Element'
    con.execute('UPDATE dimensions SET elements=?, element_count=? WHERE name=?',
                [json.dumps(values), len(values), 'Example'])
    result = dimensions.records(con, 'Example', 'elements', page=999999999)
    assert result['total'] == 10003 and result['page'] == 201 and len(result['items']) == 3
    assert result['items'][-1]['evidence'] == 'dimensions.elements[10002]'
    for query in ['last_%_', '%', '_']:
        result = dimensions.records(con, 'Example', 'elements', keyword=query)
        assert result['total'] == 1 and result['items'][0]['name'] == 'Last_%_Element'
    assert dimensions.records(con, 'Example', 'elements', keyword="' OR 1=1 --")['total'] == 0


@pytest.mark.parametrize('invalid', ['{invalid', '{"unexpected":1}', 'null', '42', '"string"'])
def test_malformed_fields_explicit_unknown(con, invalid):
    con.execute('UPDATE dimensions SET elements=?, edges=?, attributes=?, subsets=? WHERE name=?',
                [invalid] * 4 + ['Example'])
    meta = dimensions.metadata(con, 'Example')
    assert all(field['status'] == 'UNKNOWN' for field in meta['fields'].values())
    assert len(meta['warnings']) == 5
    for field in dimensions.FIELDS:
        assert dimensions.records(con, 'Example', field)['total'] == 0


def test_unknown_names_do_not_drop_records(con):
    con.execute('UPDATE dimensions SET elements=? WHERE name=?',
                [json.dumps([{}, 42, None, {'name': 42}, 'Known']), 'Example'])
    result = dimensions.records(con, 'Example', 'elements')
    assert result['total'] == 5
    assert [row['name'] for row in result['items']] == [None, None, None, None, 'Known']
    assert dimensions.metadata(con, 'Missing') is None
    with pytest.raises(ValueError):
        dimensions.records(con, 'Example', 'elements; DROP TABLE dimensions')


def test_expression_is_bounded_and_truncation_explicit(con):
    expression = 'x' * 10000
    con.execute('UPDATE dimensions SET subsets=? WHERE name=?',
                [json.dumps([dict(name='Long', expression=expression)]), 'Example'])
    item = dimensions.records(con, 'Example', 'subsets')['items'][0]
    assert item['expression_length'] == 10000 and len(item['expression']) == 8000


def test_oversized_weight_never_becomes_a_different_known_number(con):
    con.execute('UPDATE dimensions SET edges=? WHERE name=?',
                [json.dumps([dict(parent='Total', component='Income', weight=10 ** 500)]), 'Example'])
    item = dimensions.records(con, 'Example', 'edges')['items'][0]
    assert item['weight_length'] == 501 and len(item['weight']) == 240
    assert not item['weight_known']


def test_dimension_list_search_and_bounds(con):
    con.executemany('INSERT INTO dimensions (name) VALUES (?)', [(f'Dim {i:03}',) for i in range(112)])
    assert dimensions.search(con)['total'] == 113
    assert len(dimensions.search(con)['items']) == 50
    assert dimensions.search(con, 'dim 111')['items'][0]['name'] == 'Dim 111'
    assert dimensions.search(con, '%')['total'] == 0
    assert dimensions.search(con, page=999)['page'] == 3


def prepare_client(client):
    client.get('/')
    con = Store(get_settings()).connect()
    seed(con)
    con.close()


def test_workspace_html_navigation_and_source_safety(client):
    prepare_client(client)
    settings = get_settings()
    before = hashlib.sha256(settings.db_path.read_bytes()).hexdigest()
    response = client.get('/dimensions', params={'name': 'Example'})
    assert response.status_code == 200
    assert 'UNKNOWN · 类型未采集' in response.text and 'Legacy String' in response.text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text
    assert '<script>alert(1)</script>' not in response.text
    source = re.search(r'name="source" value="([a-f0-9]+)"', response.text)[1]
    edges = client.get('/dimensions', params=dict(name='Example', view='edges', element='Expense', source=source))
    assert edges.status_code == 200 and 'dimensions.edges[1]' in edges.text
    assert 'dimensions.edges[0]' not in edges.text
    assert '当前邻接记录' in edges.text
    for index, expected in [(0, '已保存 MDX，未求值'), (1, '没有已保存的静态成员清单'), (2, '未保存可识别的子集表达式')]:
        response = client.get('/dimensions', params=dict(name='Example', view='subsets', subset_index=index))
        assert response.status_code == 200 and expected in response.text
    cubes = client.get('/dimensions', params=dict(name='Example', view='cubes'))
    assert '/explorer/cube/SyntheticCube' in cubes.text
    assert '/explorer/cube/MissingCube' not in cubes.text and 'Cube 记录缺失' in cubes.text
    assert hashlib.sha256(settings.db_path.read_bytes()).hexdigest() == before
    con = Store(settings).connect()
    con.execute("UPDATE dimensions SET element_count=7 WHERE name='Example'")
    con.close()
    assert client.get('/dimensions', params=dict(name='Example', source=source)).status_code == 409


@pytest.mark.parametrize('query,code', [('name=Missing',404), ('name=Example&view=subsets&subset_index=999',404),
    ('page=0',422), ('detail_page=-1',422), ('view=unsafe',422), ('subset_index=-1',422), ('q='+'x'*1001,422)])
def test_workspace_invalid_requests(client, query, code):
    prepare_client(client)
    assert client.get('/dimensions?' + query).status_code == code


def test_source_change_during_lookup_discarded(client, tmp_path, monkeypatch):
    import shutil
    from tm1_insight.config import set_data_dir
    prepare_client(client)
    other = tmp_path / 'different-source.duckdb'
    shutil.copy2(get_settings().db_path, other)
    original = dimensions.records
    def switch(*args, **kwargs):
        result = original(*args, **kwargs)
        set_data_dir(other)
        return result
    monkeypatch.setattr(dimensions, 'records', switch)
    assert client.get('/dimensions?name=Example').status_code == 409


def test_cube_dimension_links_use_source_context(client):
    response = client.get('/explorer/cube/Sales')
    assert response.status_code == 200
    assert re.search(r'/dimensions\?name=Version&amp;source=[a-f0-9]{64}', response.text)
