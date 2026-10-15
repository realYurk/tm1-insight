"""Integration tests for the new dimension tree API and navigation reorganization."""
import json

import pytest

from test_datasource_api import client  # noqa: F401
from test_dimension_workspace import prepare_client
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store


def seed_tree(con):
    elements = [{'name': 'Total', 'type': 'Consolidated'}, {'name': 'A', 'type': 'Numeric'},
                {'name': 'B', 'type': 'Numeric'}]
    edges = [dict(parent='Total', component='A', weight=1), dict(parent='Total', component='B', weight=-1)]
    con.execute('INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)', [
        'TreeDim', 3, json.dumps(elements), '[]', json.dumps(edges), '[]'])


def prepare(client):
    prepare_client(client)
    con = Store(get_settings()).connect()
    seed_tree(con)
    con.close()


def test_tree_api_summary_and_children(client):
    prepare(client)
    source = client.get('/dimensions?name=TreeDim').text
    import re
    src = re.search(r'data-source="([a-f0-9]+)"', source).group(1)
    r = client.get(f'/api/dimensions/TreeDim/tree?source={src}')
    assert r.status_code == 200
    data = r.json()
    assert data['name'] == 'TreeDim'
    assert data['has_hierarchy'] is True
    assert [x['name'] for x in data['roots']] == ['Total']
    assert data['roots'][0]['child_count'] == 2

    r = client.get(f'/api/dimensions/TreeDim/children/Total?source={src}')
    assert r.status_code == 200
    children = r.json()['children']
    assert sorted(c['name'] for c in children) == ['A', 'B']
    weights = {c['name']: c['weight'] for c in children}
    assert weights['A'] == 1 and weights['B'] == -1

    r = client.get(f'/api/dimensions/TreeDim/search?q=A&source={src}')
    assert r.status_code == 200
    matches = {m['name']: m for m in r.json()['matches']}
    assert matches['A']['parents'] == ['Total']
    # 'A' matches 'Total' too (contains 'a'); both are correct whole-dimension hits.


def test_tree_api_404_and_source_mismatch(client):
    prepare(client)
    r = client.get('/api/dimensions/DoesNotExist/tree')
    assert r.status_code == 404
    r = client.get('/api/dimensions/TreeDim/tree?source=' + '0' * 64)
    assert r.status_code == 409


def test_dimension_page_has_tree_panel(client):
    prepare(client)
    r = client.get('/dimensions?name=TreeDim')
    assert r.status_code == 200
    assert 'id="dimension-tree"' in r.text
    assert 'dimension-tree.js' in r.text
    # Technical evidence is present but not the default emphasis
    assert '数据来源 / 原始记录' in r.text


def test_navigation_reorganization(client):
    prepare(client)
    r = client.get('/')
    assert r.status_code == 200
    text = r.text
    # 工作台 first
    assert '>工作台<' in text
    # 模型资产分组 + 四个对象 + 代码生成
    assert '模型资产' in text
    assert '/cubes' in text and '/dimensions' in text and '/processes' in text and '/chores' in text
    assert '代码生成' in text
    # 数据血缘 / 系统架构 / 高级工具 / 系统与数据
    assert '数据血缘' in text and '系统架构' in text and '高级工具' in text and '系统与数据' in text
    # 不再有「浏览模型对象」旧分组
    assert '浏览模型对象' not in text


def test_codegen_teaching_card_removed_and_four_tabs(client):
    prepare(client)
    r = client.get('/codegen')
    assert r.status_code == 200
    text = r.text
    # 教材卡片已移除
    assert 'teaching-templates' not in text
    assert '教材模板' not in text
    assert 'teaching.js' not in text
    # 顶部介绍已改为开发导向
    assert '生成常用 TI 代码草稿' in text
    # 四个 Tab 保留
    for label in ['环境初始化', '数据传输', '数据导出', '维度维护']:
        assert label in text
    # 代码生成核心交互保留
    assert 'genDataTransfer' in text and 'genDimMaintain' in text
