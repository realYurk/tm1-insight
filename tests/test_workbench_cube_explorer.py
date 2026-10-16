"""Workbench 1.1 Cube 双栏对象浏览器测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tm1_insight.api.app import app


def _sample_cube() -> str:
    from tm1_insight.store.db import Store
    from tm1_insight.config import get_settings

    store = Store(get_settings())
    con = store.connect(read_only=True)
    row = con.execute(
        "SELECT name FROM cubes WHERE name NOT LIKE '}%' ORDER BY name LIMIT 1"
    ).fetchone()
    con.close()
    return row[0] if row else ""


def test_cubes_page_dual_pane_layout():
    c = TestClient(app)
    r = c.get("/cubes")
    assert r.status_code == 200
    # 双栏容器与左侧列表 / 右侧详情占位
    assert "object-workspace" in r.text
    assert "object-browser" in r.text
    assert "object-detail" in r.text


def test_cubes_page_selected_cube_renders_detail():
    name = _sample_cube()
    if not name:
        return
    c = TestClient(app)
    from urllib.parse import quote
    r = c.get("/cubes?name=" + quote(name))
    assert r.status_code == 200
    # 右侧详情渲染了概览徽章与维度结构
    assert "cube-overview" in r.text
    assert "维度结构" in r.text
    # 选中项高亮
    assert 'aria-current="page"' in r.text


def test_cubes_page_unknown_name_404():
    c = TestClient(app)
    r = c.get("/cubes?name=__no_such_cube__")
    assert r.status_code == 404


def test_standalone_cube_view_still_works():
    """独立详情页（深链接）在抽取 include 片段后无回归。"""
    name = _sample_cube()
    if not name:
        return
    c = TestClient(app)
    from urllib.parse import quote
    r = c.get("/explorer/cube/" + quote(name))
    assert r.status_code == 200
    assert "cube-overview" in r.text
    assert 'id="rules"' in r.text
