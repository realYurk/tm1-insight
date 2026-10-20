"""分摊 API 测试：执行、对账、方案保存/加载/删除、页面路由。"""
import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from tm1_insight.api.app import app
    with TestClient(app) as c:
        yield c


def _config():
    return dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '1000000'}],
        target_rows=[{'基地': 'A', '品牌': 'X', '驱动': '100'},
                     {'基地': 'A', '品牌': 'Y', '驱动': '200'},
                     {'基地': 'A', '品牌': 'Z', '驱动': '700'}])


def test_allocation_page_served(client):
    r = client.get('/allocation')
    assert r.status_code == 200
    assert '可配置分摊' in r.text
    assert 'mermaid-viewer.js' in r.text


def test_run_ok_and_conserved(client):
    r = client.post('/api/allocation/run', json=_config())
    assert r.status_code == 200
    j = r.json()
    assert j['result']['ok'] and j['reconcile']['balanced'] == 'True'
    amounts = {x['target']['品牌']: x['allocated'] for x in j['result']['results']}
    assert amounts == {'X': '100000.00', 'Y': '200000.00', 'Z': '700000.00'}


def test_run_invalid_config_422(client):
    r = client.post('/api/allocation/run', json={'group_dimensions': []})
    assert r.status_code == 422
    assert r.json()['errors']


def test_scheme_save_load_delete(client):
    name = '自动化测试方案'
    body = dict(config=_config())
    r = client.put(f'/api/allocation/schemes/{name}', json=body)
    assert r.status_code == 200 and r.json()['saved']
    r = client.get(f'/api/allocation/schemes/{name}')
    assert r.status_code == 200 and r.json()['config']['value_field'] == '费用'
    r = client.get('/api/allocation/schemes')
    assert any(s['name'] == name for s in r.json()['schemes'])
    r = client.delete(f'/api/allocation/schemes/{name}')
    assert r.status_code == 200 and r.json()['deleted']
    assert client.get(f'/api/allocation/schemes/{name}').status_code == 404


def test_scheme_name_validation(client):
    r = client.put('/api/allocation/schemes/' + 'a' * 200, json={'config': {}})
    assert r.status_code == 422
    r = client.put('/api/allocation/schemes/../evil', json={'config': {}})
    assert r.status_code in (404, 422)  # 路径穿越被拒
