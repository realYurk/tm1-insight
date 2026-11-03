"""Retired object-workbench routes, and the one thing that survived from it.

The object page duplicated what the Cube and TI detail pages already answer in
richer form, so it is gone. What remains is the take-away Markdown: each detail
page links to it, and every retired address still lands on a real page.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from test_architecture import con  # noqa: F401  synthetic model fixture
from test_datasource_api import client  # noqa: F401  isolated app client
from tm1_insight import object_overview


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


# ---- 聚合层：仍然是交接页的唯一事实来源 ----

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


# ---- 交接导出：留在真实页面上，不再单独占一页 ----

def test_object_api_and_markdown_export(page_client):
    data = page_client.get('/api/object/cube/Cube_B').json()
    assert data['kind'] == 'cube' and data['facts'] and 'rules_text' not in data

    md = page_client.get('/api/object/cube/Cube_B/handoff.md')
    assert md.status_code == 200
    assert md.headers['content-type'].startswith('text/markdown')
    assert md.text.startswith('# Cube · Cube_B')


def test_detail_pages_offer_the_handoff_export():
    """导出入口长在真实详情页上，所以用模板契约而不是合成数据来验证。"""
    root = Path(__file__).resolve().parents[1] / 'src/tm1_insight/api/templates'
    cube = (root / '_cube_detail.html').read_text(encoding='utf-8')
    assert '/api/object/cube/' in cube and '/handoff.md' in cube and '导出交接' in cube
    ti = (root / 'process_view.html').read_text(encoding='utf-8')
    assert '/api/object/process/' in ti and '/handoff.md' in ti and '导出交接' in ti


# ---- 退役路由：一律落到真实页面，不留白屏和死链 ----

def test_retired_object_routes_land_on_real_pages(page_client):
    graph = page_client.get('/object/cube/Cube_B?view=graph')
    assert graph.url.path == '/graph' and graph.url.params.get('cube') == 'Cube_B'
    assert 'cl-root' in graph.text

    detail = page_client.get('/object/cube/Cube_B')
    assert detail.url.path == '/explorer/cube/Cube_B'

    ti = page_client.get('/object/process/Load')
    assert ti.url.path == '/explorer/process/Load'

    assert page_client.get('/object').url.path == '/cubes'
    for kind, target in (('cube', '/cubes'), ('process', '/processes'), ('chore', '/chores')):
        assert page_client.get('/browse?kind=' + kind).url.path == target


def test_lineage_has_one_home_and_ti_has_none(page_client):
    """数据流的主线只有 Cube；TI 的重复画布已经取消，落到它自己的页面。"""
    cube = page_client.get('/graph?cube=Cube_B')
    assert cube.status_code == 200 and 'id="cl-root"' in cube.text

    ti = page_client.get('/graph?ti=Load')
    assert ti.url.path == '/explorer/process/Load'

    empty = page_client.get('/graph')
    assert empty.status_code == 200 and 'id="cl-name"' in empty.text


def test_architecture_folds_back_into_the_detail_pages(page_client):
    cube = page_client.get('/architecture?name=Cube_B&kind=cube')
    assert cube.url.path == '/explorer/cube/Cube_B'

    ti = page_client.get('/architecture?name=Load&kind=process')
    assert ti.url.path == '/explorer/process/Load'

    assert page_client.get('/architecture').url.path == '/cubes'


def test_search_box_lands_on_the_matching_list(page_client):
    assert page_client.get('/search?q=cube&kind=cube').url.path == '/cubes'
    assert page_client.get('/search?q=load&kind=process').url.params.get('q') == 'load'
