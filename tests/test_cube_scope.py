"""Cube 列表的范围口径。

范围这条线一路修到计算页（2F/2G/2H）、导出（2E）、调用树（2I），
唯独 Cube 主列表还是一次性把 3338 个对象全倒出来，其中 2096 个是
} 开头的框架立方体。这一组只钉住三件事：

1. 默认不改列表语义（objects=all），但系统对象数必须随搜索结果一起报；
2. 切到 business 后，条数差正好等于报出来的系统对象数（计数自洽）；
3. 翻页/搜索不丢范围参数。

库是现搭的，不复用别处的 fixture：这一组关心的是「条数怎么算」，
底数必须由本文件自己决定，否则别人的 seed 一变，断言就在验别人的数据。
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from tm1_insight.api.app import app
from tm1_insight.config import get_settings
from tm1_insight.store import queries
from tm1_insight.store.db import Store
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for sql in ALL_TABLES.values():
        connection.execute(sql)
    for row in [
        ("Sales", "[]", "", False, 3),
        ("Sales Plan", "[]", "", False, 2),
        ("}APQ Settings", "[]", "", False, 1),
        ("}APQ Process Execution Log", "[]", "", False, 4),
        ("}ElementAttributes_Sales", "[]", "", False, 2),
    ]:
        connection.execute("INSERT INTO cubes VALUES (?,?,?,?,?)", list(row))
    yield connection
    connection.close()


def test_default_scope_keeps_everything_but_counts_system_objects(con):
    result = queries.search_cubes(con)
    names = {c["name"] for c in result["items"]}
    assert "}APQ Settings" in names, "默认范围不得擅自折叠，列表语义不能悄悄变"
    assert result["total"] == 5
    assert result["all_total"] == 5
    assert result["system_total"] == 3
    assert result["objects"] == "all"


def test_business_scope_difference_equals_reported_system_count(con):
    business = queries.search_cubes(con, objects="business")
    everything = queries.search_cubes(con, objects="all")
    assert business["total"] + business["system_total"] == everything["total"]
    assert business["all_total"] == everything["total"]
    assert all(not c["name"].startswith("}") for c in business["items"])
    # 切到业务视图后，系统对象数仍要报——看不见不等于不存在
    assert business["system_total"] == 3


def test_keyword_and_scope_stack(con):
    hit = queries.search_cubes(con, "Sales", objects="business")
    assert hit["total"] == 2 and {c["name"] for c in hit["items"]} == {"Sales", "Sales Plan"}
    # }ElementAttributes_Sales 也匹配关键词，但属于系统对象
    assert hit["system_total"] == 1
    assert hit["all_total"] == 3

    only_system = queries.search_cubes(con, "APQ", objects="business")
    assert only_system["total"] == 0
    assert only_system["system_total"] == 2, "搜索词下的系统对象数要跟着关键词走，不是全局常数"


def test_paging_happens_inside_the_scope(con):
    for i in range(6):
        con.execute("INSERT INTO cubes VALUES (?,?,?,?,?)", [f"Biz_{i}", "[]", "", False, 1])
    page1 = queries.search_cubes(con, objects="business", offset=0, limit=3)
    page2 = queries.search_cubes(con, objects="business", offset=3, limit=3)
    assert page1["total"] == 8 and len(page1["items"]) == 3
    assert [c["name"] for c in page1["items"]] == ["Biz_0", "Biz_1", "Biz_2"]
    assert [c["name"] for c in page2["items"]] == ["Biz_3", "Biz_4", "Biz_5"]


def _live_counts():
    connection = Store(get_settings()).connect(read_only=True)
    try:
        business = connection.execute(
            "SELECT count(*) FROM cubes WHERE NOT starts_with(name,'}')").fetchone()[0]
        system = connection.execute(
            "SELECT count(*) FROM cubes WHERE starts_with(name,'}')").fetchone()[0]
    finally:
        connection.close()
    return business, system


def test_cube_page_says_how_many_it_folded():
    """页面上的数字与库一致，且两种视图都能一键切换。"""
    business, system = _live_counts()
    if not system:
        pytest.skip("当前数据目录没有系统立方体，无从检验折叠文案")
    client = TestClient(app)

    folded = client.get("/cubes?objects=business")
    assert folded.status_code == 200
    assert f'<span class="tag">{business}</span>' in folded.text
    assert f"已排除 {system} 个" in folded.text
    assert "显示全部" in folded.text

    every = client.get("/cubes")
    assert every.status_code == 200
    assert f"其中 {system} 个是" in every.text
    assert "只看业务立方体" in every.text


def test_scope_survives_search_and_paging_links():
    business, system = _live_counts()
    if not business:
        pytest.skip("当前数据目录没有业务立方体")
    client = TestClient(app)
    body = client.get("/cubes?q=a&objects=business").text
    assert "objects=business" in body
    assert "objects=all" in body, "折叠视图必须给出回全量的链接"


def test_search_that_only_hits_system_objects_explains_itself():
    """搜到 0 条时不等于「没有这个东西」——可能是它只在折叠的那一侧。

    2H 在读取依赖上踩过同一个坑：把「按范围收起」说成「没有记录」。
    这里把话说全：业务侧 0 条、系统侧命中 N 条，且给出去全部看的入口。
    """
    business, system = _live_counts()
    if not system:
        pytest.skip("当前数据目录没有系统立方体")
    connection = Store(get_settings()).connect(read_only=True)
    try:
        name = connection.execute(
            "SELECT name FROM cubes WHERE starts_with(name,'}') ORDER BY name LIMIT 1").fetchone()[0]
    finally:
        connection.close()
    body = TestClient(app).get("/cubes", params={"q": name, "objects": "business"}).text
    assert "没有匹配的业务 Cube" in body
    assert "系统立方体匹配" in body
    assert "在全部里看" in body
