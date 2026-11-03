"""Contracts for the object workbench: one object, one URL, five answers."""
from __future__ import annotations

import pytest

from test_architecture import con  # noqa: F401  synthetic model fixture
from test_datasource_api import client  # noqa: F401  isolated app client
from test_datasource_api import client  # noqa: F401  isolated app client
from tm1_insight import object_overview


@pytest.fixture(autouse=True)
def _relations(con):
    """The architecture fixture defines code, not the indexed relation tables."""
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")


@pytest.fixture(autouse=True)
def _relations(con):
    """The architecture fixture defines code, not the indexed relation tables."""
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")


class _Shared:
    """Give the router the fixture connection without letting it close it."""

    def __init__(self, con):
        self._con = con

    def execute(self, *args, **kwargs):
        return self._con.execute(*args, **kwargs)

    def close(self):
        pass


@pytest.fixture
def page_client(client, con, monkeypatch):
    from tm1_insight.api import object_pages
    monkeypatch.setattr(object_pages, "_connect", lambda: _Shared(con))
    return client


def test_cube_overview_answers_without_guessing(con):
    item = object_overview.build(con, 'cube', 'cube_b')
    assert item['name'] == 'Cube_B'  # canonical spelling, not the queried casing
    assert item['kind'] == 'cube'
    assert {'key': 'writers', 'label': '写入 TI', 'value': 1} in item['facts']
    assert 'Cube_A' in item['upstream']  # written by Load, which reads Cube_A
    assert item['writers'] == ['Load']
    assert any('前端' in note for note in item['issues'])
    assert item['position'] and item['position']['total'] >= 1


def test_process_overview_counts_and_entry_points(con):
    item = object_overview.build(con, 'process', 'load')
    assert item['name'] == 'Load'
    assert item['writes'] == ['Cube_B'] and item['reads'] == ['Cube_A']
    assert item['callers'] == ['Caller']
    # 调度挂在调用方 Caller 上，不能自动算到被调用的 Load 名下。
    assert item['chores'] == []


def test_missing_object_is_absent_not_invented(con):
    assert object_overview.build(con, 'cube', 'No Such Cube') is None
    assert object_overview.build(con, 'process', 'No Such TI') is None


def test_handoff_is_readable_and_bounded(con):
    item = object_overview.build(con, 'cube', 'Cube_B')
    text = object_overview.handoff_markdown(item)
    assert text.startswith('# Cube · Cube_B')
    assert '## 口径' in text and '未执行 TI' in text
    assert '资产信号' in text
    assert '\n## 上下游' in text


def test_object_page_tabs_are_url_state(page_client):
    import re
    base = '/object/cube/Cube_B'
    overview = page_client.get(base)
    assert overview.status_code == 200
    tabs = [t.strip() for t in re.findall(r'object-tab[^>]*>([^<]+)', overview.text) if t.strip()]
    assert tabs == ['概览', '关系图', '数据形成', '实现', '交接']
    assert 'object-facts' in overview.text

    graph = page_client.get(base + '?view=graph')
    assert 'id="cl-root"' in graph.text and 'data-object-base="/object/cube"' in graph.text
    assert 'id="cl-name"' in graph.text and 'value="Cube_B"' in graph.text

    formation = page_client.get(base + '?view=formation')
    assert 'id="fa-root"' in formation.text and 'data-formation-autostart="true"' in formation.text

    code = page_client.get(base + '?view=code')
    assert 'object-code' in code.text or '没有 Rule 文本' in code.text

    handoff = page_client.get(base + '?view=handoff')
    assert 'object-handoff-text' in handoff.text and '## 口径' in handoff.text

    # Unknown view falls back to the default answer instead of an empty shell.
    fallback = page_client.get(base + '?view=nope')
    assert 'object-facts' in fallback.text and 'fa-root' not in fallback.text


def test_process_object_page_has_no_formation_tab(page_client):
    import re
    html = page_client.get('/object/process/Load').text
    assert [t.strip() for t in re.findall(r'object-tab[^>]*>([^<]+)', html) if t.strip()] == ['概览', '调用关系', '实现', '交接']


def test_legacy_routes_land_on_the_same_state(page_client):
    graph = page_client.get('/graph?cube=Cube_B')
    assert graph.status_code == 200
    assert graph.url.path == '/object/cube/Cube_B'
    assert graph.url.params.get('view') == 'graph'

    arch = page_client.get('/architecture?name=Cube_B&kind=cube')
    assert arch.url.path == '/object/cube/Cube_B' and arch.url.params.get('view') == 'formation'

    process = page_client.get('/architecture?name=Load&kind=process')
    assert process.url.path == '/object/process/Load'

    landing = page_client.get('/graph')
    assert landing.url.path == '/object' and '找一个对象' in landing.text


def test_unknown_object_returns_a_search_page_not_a_fake_page(page_client):
    response = page_client.get('/object/cube/No%20Such%20Cube')
    assert response.status_code == 404
    assert '没有这个对象' in response.text


def test_object_api_and_markdown_export(page_client):
    data = page_client.get('/api/object/cube/Cube_B').json()
    assert data['kind'] == 'cube' and data['facts'] and 'rules_text' not in data

    md = page_client.get('/api/object/cube/Cube_B/handoff.md')
    assert md.status_code == 200
    assert md.headers['content-type'].startswith('text/markdown')
    assert md.text.startswith('# Cube · Cube_B')


def test_catalog_single_entry_for_four_object_kinds(page_client):
    for kind in ('cube', 'process', 'dimension', 'chore'):
        response = page_client.get('/browse?kind=' + kind)
        assert response.status_code == 200
        assert 'catalog-list' in response.text
