"""Bounded audit navigation and metadata-confirmed draft generation; synthetic only."""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

import duckdb
import pytest

from test_datasource_api import client  # noqa: F401
from tm1_insight.config import get_settings
from tm1_insight.store import queries
from tm1_insight.store.db import Store
from tm1_insight.store.schema import AUDIT_TABLES


def seed_audit(con, count=1128):
    con.executemany("INSERT INTO excel_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (f"Menu {i:04}", f"file-{i:04}.xlsx", "Broken Link" if i % 10 == 0 else "Excel",
         "高" if i % 2 == 0 else "低", "synthetic", "", i % 2 == 0, i)
        for i in range(count)])
    con.executemany("INSERT INTO front_backend_mapping VALUES (?, ?, ?, ?)", [
        (f"Menu {i:04}", f"file-{i:04}.xlsx", "Sales" if i < count - 1 else "Only Last Cube", 1)
        for i in range(count)])


@pytest.fixture
def audit_con():
    con = duckdb.connect()
    for ddl in AUDIT_TABLES.values():
        con.execute(ddl)
    seed_audit(con)
    yield con
    con.close()


def test_audit_pages_cover_all_records_without_duplicates(audit_con):
    seen = []
    for page in range(1, 24):
        result = queries.audit_page(audit_con, kind="assets", page=page)
        assert result["total"] == 1128 and result["pages"] == 23
        assert len(result["items"]) <= 50
        seen.extend(row["blob_name"] for row in result["items"])
    assert len(seen) == len(set(seen)) == 1128
    assert queries.audit_page(audit_con, kind="assets", page=9999)["page"] == 23
    assert len(queries.audit_page(audit_con, kind="assets", limit=9999)["items"]) == 100


def test_audit_search_filters_apply_before_pagination(audit_con):
    result = queries.audit_page(audit_con, kind="assets", keyword="FILE-1127")
    assert result["total"] == 1 and result["items"][0]["blob_name"] == "file-1127.xlsx"
    result = queries.audit_page(audit_con, kind="assets", risk="高", only_tm1=True, only_broken=True)
    assert result["total"] == 113
    assert all(row["asset_type"] == "Broken Link" and row["has_tm1"] for row in result["items"])
    result = queries.audit_page(audit_con, kind="mappings", keyword="only last cube")
    assert result["total"] == 1 and result["items"][0]["excel_file"] == "file-1127.xlsx"
    for literal in ("%", "_", "' OR 1=1 --"):
        assert queries.audit_page(audit_con, kind="assets", keyword=literal)["total"] == 0
    assert queries.audit_summary(audit_con) == dict(
        total_assets=1128, total_mappings=1128, with_tm1=564, risk_high=564, broken_link=113)


def test_audit_html_bounded_and_source_aware(client):
    from tm1_insight.audit_workspace import workspace
    client.get('/')
    settings = get_settings()
    before = hashlib.sha256(settings.db_path.read_bytes()).hexdigest()
    local = workspace(settings, initialize=True)
    con = Store(local).connect()
    seed_audit(con)
    con.close()
    response = client.get('/audit')
    assert response.status_code == 200
    assert len(re.findall(r'<tr data-risk=', response.text)) == 50
    assert len(re.findall(r'<tr data-search=', response.text)) == 50
    assert '第 1 / 23 页' in response.text and '1128 个资产' in response.text
    token = re.search(r'name="source" value="([a-f0-9]+)"', response.text)[1]
    page2 = client.get('/audit', params=dict(source=token, asset_page=2, mapping_q='Sales', tm1='true'))
    assert page2.status_code == 200 and 'file-0100.xlsx' in page2.text
    import html
    link = html.unescape(re.search(r'href="([^"]+)"[^>]*>下一页资产', page2.text)[1])
    params = parse_qs(urlsplit(link).query)
    assert params['asset_page'] == ['3'] and params['mapping_q'] == ['Sales'] and params['tm1'] == ['true']
    found = client.get('/audit', params={'asset_q': 'file-1127'})
    assert 'file-1127.xlsx' in found.text and '筛选结果 1 条' in found.text
    con = Store(local).connect()
    con.execute("INSERT INTO excel_assets (blob_name) VALUES ('new-result.xlsx')")
    con.close()
    assert client.get('/audit', params={'source': token}).status_code == 409
    assert client.get('/audit').status_code == 200
    assert hashlib.sha256(settings.db_path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('query', ['asset_page=0', 'mapping_page=-1', 'risk=unsafe', 'asset_q=' + 'x' * 1001])
def test_audit_rejects_invalid_filters(client, query):
    assert client.get('/audit?' + query).status_code == 422


def load_structure(client, src='Sales', tgt='Budget'):
    sj = client.post('/api/codegen/cube-dims', json={'cube': src}).json()
    tj = client.post('/api/codegen/cube-dims', json={'cube': tgt}).json()
    assert sj['source'] == tj['source']
    return dict(source=sj['source'], src_dims=sj['dims'], tgt_dims=tj['dims'])


def test_codegen_confirmed_structure_and_legacy_api(client):
    client.get('/')
    con = Store(get_settings()).connect(read_only=True)
    try:
        cubes = [r[0] for r in con.execute('SELECT name FROM cubes').fetchall()]
    finally:
        con.close()
    src, tgt = cubes[:2]
    structure = load_structure(client, src, tgt)
    body = dict(src_cube=src, tgt_cube=tgt, structure=structure, operation='CellPutN')
    result = client.post('/api/codegen/data-transfer', json=body)
    assert result.status_code == 200
    output = result.json()
    assert output['src_dims'] == structure['src_dims'] and output['tgt_dims'] == structure['tgt_dims']
    assert [m['tgt_dim'] for m in output['mapping']] == structure['tgt_dims']
    assert 'CellPutN(vValue, cCubTgt,' in output['data']
    # Existing callers need not adopt the additive structure field.
    assert client.post('/api/codegen/data-transfer', json=dict(src_cube=src, tgt_cube=tgt)).status_code == 200
    body['structure']['tgt_dims'] = ['Invented Dimension']
    assert client.post('/api/codegen/data-transfer', json=body).status_code == 409


def test_codegen_rejects_stale_metadata_and_unknown_cubes(client):
    client.get('/')
    structure = load_structure(client, 'Sales', 'Sales')
    body = dict(src_cube='Sales', tgt_cube='Sales', structure=structure)
    con = Store(get_settings()).connect()
    con.execute("UPDATE cube_has_dimension SET dim_order = dim_order + 10 WHERE cube_name = 'Sales'")
    con.close()
    assert client.post('/api/codegen/data-transfer', json=body).status_code == 409
    assert client.post('/api/codegen/cube-dims', json={'cube': 'Missing'}).status_code == 400
    assert client.post('/api/codegen/data-transfer', json=dict(src_cube='Sales', tgt_cube='Missing')).status_code == 400


def test_codegen_rejects_wrong_filter_and_operation(client):
    for extra in [dict(operation='ExecuteProcess'), dict(src_filters=[{'dim': 'Missing'}]), dict(tgt_filters=['bad'])]:
        result = client.post('/api/codegen/data-transfer', json=dict(src_cube='Sales', tgt_cube='Sales', **extra))
        assert result.status_code == 400


def test_codegen_rejects_another_source_with_identical_dimensions(client, tmp_path):
    import shutil
    client.get('/')
    structure = load_structure(client, 'Sales', 'Sales')
    other = tmp_path / 'another-model.duckdb'
    shutil.copy2(get_settings().db_path, other)
    assert client.post('/api/datasource/use', json={'source': 'local', 'path': str(other)}).status_code == 200
    response = client.post('/api/codegen/data-transfer', json=dict(
        src_cube='Sales', tgt_cube='Sales', structure=structure))
    assert response.status_code == 409


@pytest.mark.parametrize('endpoint', ['cube-dims', 'data-transfer'])
def test_codegen_discards_result_if_source_changes_during_request(client, tmp_path, monkeypatch, endpoint):
    import shutil
    from tm1_insight.config import set_data_dir
    from tm1_insight.store import codegen
    client.get('/')
    settings = get_settings()
    other = tmp_path / 'switched-during-request.duckdb'
    shutil.copy2(settings.db_path, other)
    function = '_cube_dims' if endpoint == 'cube-dims' else 'data_transfer'
    original = getattr(codegen, function)
    def switch_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        set_data_dir(other)
        return result
    monkeypatch.setattr(codegen, function, switch_after_read)
    body = {'cube': 'Sales'} if endpoint == 'cube-dims' else {'src_cube': 'Sales', 'tgt_cube': 'Sales'}
    assert client.post('/api/codegen/' + endpoint, json=body).status_code == 409


def test_codegen_unknown_mapping_stays_explicit(client):
    client.get('/')
    con = Store(get_settings()).connect()
    con.execute("INSERT INTO cubes (name) VALUES ('SyntheticTarget')")
    con.execute("INSERT INTO cube_has_dimension VALUES ('SyntheticTarget', 'UnmappedDimension', 0)")
    con.close()
    result = client.post('/api/codegen/data-transfer', json=dict(src_cube='Sales', tgt_cube='SyntheticTarget')).json()
    assert result['mapping'] == [dict(tgt_dim='UnmappedDimension', tgt_idx=0, src_idx=None, auto=False)]
    assert "vUnmappedDimension = '';" in result['data']
