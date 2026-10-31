"""阶段 2：调用事实的唯一口径。

采集阶段把调用写进三张表，页面原先各读各的，于是同一个 TI 在页头
说「被 3 个进程调用」、在调用树里只显示 2 个（真实 Demo 库上 113 个 TI 不一致）。
本文件守住 `store.calls` 作为唯一生产者的契约：

1. 三张来源表合并去重，同一条调用只算一次；
2. 目标是字面 / 框架 / 目录中不存在 / 动态，四类必须分开，动态不能当进程名；
3. 页头计数、调用树、学习报告三处对同一个 TI 给出同一个调用方集合；
4. 自环被画图逻辑跳过后必须显式说明，不能静默消失。

全部使用合成模型，不读取也不写入 data/ 下的任何真实库。
"""
import importlib
import re

import duckdb
import pytest
from fastapi.testclient import TestClient

import tm1_insight.config as config
import tm1_insight.datasource as ds
from tm1_insight.store import calls, queries
from tm1_insight.store.schema import ALL_TABLES


def insert_process(con, name, prolog="", data=""):
    con.execute("INSERT INTO processes VALUES (?, ?, ?, ?, ?, '[]', 'null', ?)",
                [name, prolog, "", data, "", len(prolog + data)])


def literal(con, caller, callee):
    con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [caller, callee])


def business(con, caller, callee, params=None):
    con.execute("INSERT INTO ti_business_calls VALUES (?, ?, ?)", [caller, callee, params])


def framework(con, caller, callee, purpose=""):
    con.execute("INSERT INTO ti_framework_calls VALUES (?, ?, ?)", [caller, callee, purpose])


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for ddl in ALL_TABLES.values():
        connection.execute(ddl)
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# 分类：四类目标必须分开，不能混成「进程名」
# ---------------------------------------------------------------------------

def test_three_sources_merge_into_one_classified_edge_set(con):
    for name in ("A", "B", "Target"):
        insert_process(con, name)
    literal(con, "A", "B")                       # 正则表：字面调用
    business(con, "A", "Target")                 # 变量解析表：目标确实存在
    framework(con, "A", "}bedrock.cube.data.clear", "清空目标 Cube")
    literal(con, "A", "Ghost")                   # 字面写了，但目录里没有
    business(con, "A", "<sProc2>")               # 变量没解析出来

    summary = calls.summary(con, "A")
    by_name = {e["callee"]: e["kind"] for e in summary["callees"]}

    assert by_name == {
        "B": calls.KIND_LITERAL,
        "Target": calls.KIND_LITERAL,
        "}bedrock.cube.data.clear": calls.KIND_FRAMEWORK,
        "Ghost": calls.KIND_MISSING,
        "<sProc2>": calls.KIND_DYNAMIC,
    }
    assert summary["counts"]["callees"] == {
        calls.KIND_LITERAL: 2, calls.KIND_FRAMEWORK: 1,
        calls.KIND_MISSING: 1, calls.KIND_DYNAMIC: 1,
    }
    # 只有三类能当节点；动态目标不在其中。
    assert {e["callee"] for e in summary["node_callees"]} == {
        "B", "Target", "}bedrock.cube.data.clear", "Ghost",
    }


def test_same_call_recorded_in_two_tables_counts_once(con):
    for name in ("A", "B"):
        insert_process(con, name)
    literal(con, "A", "B")
    business(con, "A", "B", "{}")
    framework(con, "A", "B", "不该在这里")

    summary = calls.summary(con, "A")
    assert [e["callee"] for e in summary["callees"]] == ["B"]
    assert summary["callees"][0]["kind"] == calls.KIND_LITERAL
    # detail 取非空的一侧，不因去重丢掉参数/用途
    assert summary["callees"][0]["detail"] in ("{}", "不该在这里")


def test_missing_sources_degrade_instead_of_failing(con):
    """旧快照可能没有 ti_business_calls / ti_framework_calls，少读一份即可。"""
    con.execute("DROP TABLE ti_business_calls")
    con.execute("DROP TABLE ti_framework_calls")
    insert_process(con, "A")
    insert_process(con, "B")
    literal(con, "A", "B")
    assert calls.available_sources(con) == ("process_calls_process",)
    assert [e["callee"] for e in calls.summary(con, "A")["callees"]] == ["B"]


# ---------------------------------------------------------------------------
# 页面与树：同一个 TI 必须给出同一个调用方集合
# ---------------------------------------------------------------------------

def test_business_only_caller_appears_in_both_header_and_tree(con):
    """真实库里 113 个 TI 的页头计数大于树计数，根因是树只读正则表。"""
    insert_process(con, "OnlyInBusiness")
    insert_process(con, "Hub")
    business(con, "OnlyInBusiness", "Hub")

    summary = calls.summary(con, "Hub")
    tree = queries.process_call_tree(con, "Hub")

    assert summary["callers"] == ["OnlyInBusiness"]
    assert tree["direct"]["callers"]["total"] == 1
    assert [n["name"] for n in tree["callers"]] == ["OnlyInBusiness"]
    assert tree["direct"]["callers"]["shown"] == len(summary["callers"])


def test_dynamic_target_never_becomes_a_clickable_node(con):
    insert_process(con, "Caller")
    business(con, "Caller", "<sProc2>")
    business(con, "Caller", "Real")

    tree = queries.process_call_tree(con, "Caller")
    names = [n["name"] for n in tree["callees"]]
    assert "<sProc2>" not in names
    assert "Real" in names
    assert tree["dynamic_targets"] == 1


def test_missing_and_framework_nodes_are_labelled(con):
    insert_process(con, "Caller")
    literal(con, "Caller", "Ghost")
    framework(con, "Caller", "}bedrock.cube.data.clear")

    tree = queries.process_call_tree(con, "Caller")
    kinds = {n["name"]: n["kind"] for n in tree["callees"]}
    assert kinds["Ghost"] == calls.KIND_MISSING
    assert kinds["}bedrock.cube.data.clear"] == calls.KIND_FRAMEWORK

    html = _render_fragment(tree)
    assert "目录中无此 TI" in html
    # 目录里没有的 TI 不能给一个点了会 404 的链接
    assert "/explorer/process/Ghost" not in html
    assert "框架" in html


def test_self_loop_is_disclosed_not_dropped(con):
    insert_process(con, "Recursive")
    literal(con, "Recursive", "Recursive")

    tree = queries.process_call_tree(con, "Recursive")
    assert tree["recursive_self_call"] is True
    assert tree["callers"] == [] and tree["callees"] == []   # 不画自环
    assert "调用自己" in _render_fragment(tree)


def test_cycle_is_expanded_once_per_direction(con):
    for name in ("A", "B", "C"):
        insert_process(con, name)
    literal(con, "A", "B")
    literal(con, "B", "C")
    literal(con, "C", "A")

    tree = queries.process_call_tree(con, "A")
    # 下游 A→B→C，C→A 被 visited 挡住
    assert [n["name"] for n in tree["callees"]] == ["B"]
    assert [n["name"] for n in tree["callees"][0]["children"]] == ["C"]
    # 上游 A←C←B
    assert [n["name"] for n in tree["callers"]] == ["C"]


def _render_fragment(tree):
    """用真实模板渲染片段，避免测试只验证数据结构、不验证页面上写了什么。"""
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    templates = Path(__file__).resolve().parents[1] / "src" / "tm1_insight" / "api" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)), autoescape=True)
    return env.get_template("_call_tree.html").render(call_tree=tree)


# ---------------------------------------------------------------------------
# 页面级：一个只有「变量解析表」记录的调用方，页头与片段必须一致
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "app")
    monkeypatch.setattr(config, "_DATA_DIR_OVERRIDE", None)
    monkeypatch.setattr(ds, "_source_cache", None)
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    config.get_settings.cache_clear()
    ds.load_demo_data()
    from tm1_insight.api.app import app
    with duckdb.connect(str(config.get_settings().db_path)) as connection:
        # Hub 的调用方只写在变量解析表里 —— 正是真实库中 113 个不一致 TI 的形态
        insert_process(connection, "Hub", prolog="vX = 1;")
        insert_process(connection, "ViaVariable", prolog="sProc = 'Hub';\nExecuteProcess(sProc);")
        business(connection, "ViaVariable", "Hub")
        # Callee 有动态目标，页头与树都要如实说明未解析
        insert_process(connection, "Dynamic", prolog="ExecuteProcess(sProc2);")
        insert_process(connection, "Elsewhere", prolog="vY = 2;")
        business(connection, "Dynamic", "<sProc2>")
        business(connection, "Dynamic", "Elsewhere")
    api_module = importlib.import_module("tm1_insight.api.app")
    api_module._call_tree_cache.clear()
    with TestClient(app) as test_client:
        yield test_client
    api_module._call_tree_cache.clear()
    config.get_settings.cache_clear()


def test_header_count_matches_tree_for_variable_resolved_caller(client):
    page = client.get("/explorer/process/Hub")
    assert page.status_code == 200
    assert "被 1 个进程调用" in page.text

    fragment = client.get("/explorer/process/Hub/call-tree")
    assert fragment.status_code == 200
    assert "被调用（1）" in fragment.text
    assert "ViaVariable" in fragment.text


def test_dynamic_call_is_counted_in_header_and_explained_in_tree(client):
    page = client.get("/explorer/process/Dynamic")
    assert "1 处动态调用目标未解析" in page.text

    fragment = client.get("/explorer/process/Dynamic/call-tree")
    assert "1 处调用目标是从变量或表达式拼出来的" in fragment.text
    assert "&lt;sProc2&gt;" not in fragment.text
    assert "<sProc2>" not in fragment.text


def test_learning_report_uses_the_same_callers(client):
    """学习报告与 TI 页共用调用口径，不允许各读一张表。"""
    from tm1_insight.learning.engine import build_report

    con = duckdb.connect(str(config.get_settings().db_path), read_only=True)
    try:
        report = build_report(con, query="Hub")
    finally:
        con.close()
    entry = next(p for p in report["processes"] if p["process"] == "Hub")
    assert "ViaVariable" in entry["called_by"]


# ---------------------------------------------------------------------------
# 证据可见：数字必须能拆回来源表，否则「更准了」无法被使用者核对
# ---------------------------------------------------------------------------

def test_source_breakdown_shows_which_table_produced_each_caller(con):
    """页头那个数字必须能拆到来源表；同一次调用被两表记录时只算一个调用方。"""
    for name in ("Hub", "Literal", "Var", "Fw"):
        insert_process(con, name)
    literal(con, "Literal", "Hub")
    business(con, "Var", "Hub")
    framework(con, "Fw", "Hub")
    literal(con, "Fw", "Hub")          # 同一调用方被两张表记录

    summary = calls.summary(con, "Hub")
    assert summary["counts"]["callers"] == 3, "调用方必须按名字去重，不能按行数"
    assert summary["callers_by_source"] == {
        calls.SRC_REGEX: 2, calls.SRC_RESOLVED: 1, calls.SRC_FRAMEWORK: 1,
    }
    # 各来源之和 4 > 去重后 3：页面必须说明「可重叠」，否则会被人相加
    assert sum(summary["callers_by_source"].values()) > summary["counts"]["callers"]


def test_edge_carries_primary_source_and_all_sources(con):
    for name in ("Hub", "Fw"):
        insert_process(con, name)
    framework(con, "Fw", "Hub")
    literal(con, "Fw", "Hub")

    edge = calls.edges(con, caller="Fw", callee="Hub")[0]
    assert edge["source"] == calls.SRC_REGEX, "字面写死是最硬证据，优先展示"
    assert set(edge["sources"]) == {calls.SRC_REGEX, calls.SRC_FRAMEWORK}


def test_target_counts_separate_old_scope_from_merged_scope(con):
    """全模型对照：旧口径（只有正则表）与新口径（三表合并）并排，且标出动态占位。"""
    for name in ("Hub", "Literal", "Fw"):
        insert_process(con, name)
    literal(con, "Literal", "Hub")
    framework(con, "Fw", "Hub")
    business(con, "Literal", "<sProc2>")

    rows = {row["callee"]: row for row in calls.caller_counts_by_target(con)}
    hub = rows["Hub"]
    assert (hub["regex"], hub["framework"], hub["total"], hub["delta"]) == (1, 1, 2, 1)
    assert rows["<sProc2>"]["dynamic"] is True, "变量占位必须被标成不是成员"
    assert hub["dynamic"] is False


def test_header_and_sources_page_explain_the_numbers(client):
    """页面上必须能点开看到拆解，并且差异清单能落到具体对象。"""
    page = client.get("/explorer/process/Hub")
    assert page.status_code == 200
    assert "这些调用数字是怎么来的" in page.text
    assert "正则扫源码" in page.text and "框架调用表" in page.text
    assert "不是运行证据" in page.text
    assert "/calls/sources" in page.text

    sources = client.get("/calls/sources")
    assert sources.status_code == 200
    assert sources.headers["cache-control"] == "no-store"
    assert "Hub" in sources.text, "有差异的对象必须出现在清单里"
    # 占位名会按 HTML 转义展示，不能直接渲染成标签
    assert "&lt;sProc2&gt;" in sources.text, "占位条目也要列出，但必须标注"
    assert "动态占位" in sources.text


def test_sources_page_marks_focus_object(client):
    page = client.get("/calls/sources", params={"focus": "Hub"})
    assert 'class="row-focus"' in page.text


def test_tree_legend_states_what_the_nodes_are(con):
    for name in ("Root", "Literal", "Ghost"):
        insert_process(con, name)
    literal(con, "Literal", "Root")
    literal(con, "GhostOnly", "Root")      # 目录里没有 GhostOnly，但它是调用方
    literal(con, "Root", "Ghost")

    tree = queries.process_call_tree(con, "Root")
    assert tree["kind_counts"][calls.KIND_MISSING] == 1
    fragment = _render_fragment(tree)
    assert "图中节点" in fragment
    assert "目录中不存在 1 个" in fragment
