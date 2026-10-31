"""采集范围：``}`` 开头的系统对象默认不进快照。

这件事的风险不在于「少收几个对象」，而在于一旦只说「没收」，下游就会把
``}bedrock.cube.data.clear`` 判成「目录中不存在」——把采集配置说成数据事实。
本文件守住三条线：

1. 对象正文不收录，但名字进 ``excluded_objects``；
2. 被排除目标的调用边照旧存在，分类仍是 framework，不是 missing；
3. 页面上这类节点写明「按采集范围未收录」，且不给一个点了会 404 的链接。

全部使用内存库与假 client，不连 TM1、不读写 data/ 下的真实库。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from tm1_insight.collector import TM1Collector
from tm1_insight.ingest.loader import Loader
from tm1_insight.ingest.scope import EXCLUDED_REASON, is_system_object, split_by_scope
from tm1_insight.store import calls, queries
from tm1_insight.store.schema import ALL_TABLES


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _loader():
    """绕过 Settings 构造：只测「读清单 → 建表」这一段，不需要真实配置。"""
    loader = Loader.__new__(Loader)
    loader._excluded = set()
    return loader


def _raw_process(name):
    return {"name": name, "prolog": "", "metadata": "", "data": "", "epilog": "",
            "parameters": [], "datasource": None}


class _Client:
    """只提供 collector 需要的最小面；不连 TM1。"""

    def __init__(self, process_names):
        self.names = {"cubes": [], "processes": list(process_names),
                      "dimensions": [], "chores": []}

    def list_all_names(self):
        return self.names

    def fetch_process(self, tm1, name):
        return _raw_process(name)

    def fetch_cube(self, tm1, name):          # pragma: no cover - 本文件不用
        return {"name": name, "dimensions": [], "rules": ""}

    def fetch_dimension(self, tm1, name, is_system):   # pragma: no cover
        return {"name": name, "elements": [], "subsets": []}


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for ddl in ALL_TABLES.values():
        connection.execute(ddl)
    yield connection
    connection.close()


def insert_process(con, name):
    con.execute("INSERT INTO processes VALUES (?, '', '', '', '', '[]', 'null', 0)", [name])


def literal(con, caller, callee):
    con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [caller, callee])


def framework(con, caller, callee):
    con.execute("INSERT INTO ti_framework_calls VALUES (?, ?, '')", [caller, callee])


def render_fragment(tree):
    from jinja2 import Environment, FileSystemLoader

    templates = Path(__file__).resolve().parents[1] / "src" / "tm1_insight" / "api" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)), autoescape=True)
    return env.get_template("_call_tree.html").render(call_tree=tree)


# ---------------------------------------------------------------------------
# 一、采集范围本身
# ---------------------------------------------------------------------------

def test_scope_splits_on_leading_brace_only():
    names = {"processes": ["Good.TI", "}bedrock.cube.data.clear", "A}B"],
             "cubes": ["Sales", "}Stats"]}
    kept, excluded = split_by_scope(names, include_system=False)

    assert kept["processes"] == ["Good.TI", "A}B"], "只在开头才算系统对象，中间出现不算"
    assert kept["cubes"] == ["Sales"]
    assert excluded == {"processes": ["}bedrock.cube.data.clear"], "cubes": ["}Stats"]}


def test_include_system_keeps_everything():
    names = {"processes": ["A", "}bedrock.x"]}
    kept, excluded = split_by_scope(names, include_system=True)
    assert kept == names and excluded == {}


def test_is_system_object_does_not_guess_by_name_shape():
    assert is_system_object("}bedrock.cube.data.clear")
    assert not is_system_object("APQ.Something")   # 看着像框架，但没有 } 前缀
    assert not is_system_object("")
    assert not is_system_object(None)


def test_collector_omits_system_objects_and_reports_them():
    """默认采集：不拉 } 对象的正文，但把名字交出来。"""
    client = _Client(["Biz.TI", "}bedrock.cube.data.clear"])
    payload = TM1Collector(client).collect_snapshot()

    assert [p["name"] for p in payload["processes"]] == ["Biz.TI"]
    assert payload["excluded"] == {"processes": ["}bedrock.cube.data.clear"]}


def test_collector_can_still_collect_system_objects_on_request():
    client = _Client(["Biz.TI", "}bedrock.cube.data.clear"])
    payload = TM1Collector(client).collect_snapshot(include_system=True)
    assert len(payload["processes"]) == 2
    assert "excluded" not in payload


# ---------------------------------------------------------------------------
# 二、导入：排除名单必须落成表
# ---------------------------------------------------------------------------

def test_loader_records_excluded_names(tmp_path, con):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "_excluded.json").write_text(
        json.dumps({"processes": ["}bedrock.a", "}bedrock.b"], "cubes": ["}Stats"]}),
        encoding="utf-8",
    )

    _loader()._insert_excluded(con, raw)
    rows = con.execute("SELECT name, kind, reason FROM excluded_objects ORDER BY name").fetchall()

    assert [r[0] for r in rows] == ["}Stats", "}bedrock.a", "}bedrock.b"]
    assert {r[1] for r in rows} == {"processes", "cubes"}
    assert all(r[2] == EXCLUDED_REASON for r in rows)


def test_missing_excluded_file_is_not_an_error(tmp_path, con):
    raw = tmp_path / "raw"
    raw.mkdir()
    _loader()._insert_excluded(con, raw)         # 旧采集包没有这份清单
    assert con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0] == 0


def test_duplicate_names_across_kinds_are_inserted_once(tmp_path, con):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "_excluded.json").write_text(
        json.dumps({"processes": ["}bedrock.a"], "cubes": ["}bedrock.a"]}), encoding="utf-8")
    _loader()._insert_excluded(con, raw)
    assert con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# 三、事实层：未收录 ≠ 不存在
# ---------------------------------------------------------------------------

def test_framework_target_outside_catalog_is_not_reported_missing(con):
    """框架对象不进快照后，指向它的边仍然是 framework，不能降级成 missing。"""
    insert_process(con, "Caller")
    con.execute("INSERT INTO excluded_objects VALUES ('}bedrock.cube.data.clear', 'processes', ?)",
                [EXCLUDED_REASON])
    framework(con, "Caller", "}bedrock.cube.data.clear")

    edge = calls.edges(con, caller="Caller")[0]
    assert edge["kind"] == calls.KIND_FRAMEWORK, "按范围未收录，不是「源码写错名字」"
    assert edge["in_catalog"] is False

    tree = queries.process_call_tree(con, "Caller")
    node = tree["callees"][0]
    assert node["catalog"] == "excluded"
    assert tree["catalog_counts"]["excluded"] == 1
    assert tree["catalog_counts"]["missing"] == 0


def test_truly_absent_business_target_is_still_missing(con):
    """非 } 目标不在目录，才是真的「目录中没有」——两类必须分开。"""
    insert_process(con, "Caller")
    literal(con, "Caller", "Ghost")

    tree = queries.process_call_tree(con, "Caller")
    assert tree["callees"][0]["catalog"] == "missing"
    assert tree["catalog_counts"]["missing"] == 1


def test_tree_page_says_not_collected_instead_of_does_not_exist(con):
    insert_process(con, "Caller")
    con.execute("INSERT INTO excluded_objects VALUES ('}bedrock.cube.data.clear', 'processes', ?)",
                [EXCLUDED_REASON])
    framework(con, "Caller", "}bedrock.cube.data.clear")
    # 显式展开系统对象，否则它会被范围折叠掉，测不到节点文案
    tree = queries.process_call_tree(con, "Caller", include_system=True)
    html = render_fragment(tree)

    assert "未收录" in html
    assert "目录中无此 TI" not in html
    assert "/explorer/process/%7Dbedrock" not in html, "点开必 404 的链接不能给"


def test_tree_lists_how_many_nodes_were_not_collected(con):
    insert_process(con, "Caller")
    for name in ("}bedrock.a", "}bedrock.b"):
        con.execute("INSERT INTO excluded_objects VALUES (?, 'processes', ?)",
                    [name, EXCLUDED_REASON])
        framework(con, "Caller", name)
    tree = queries.process_call_tree(con, "Caller", include_system=True)
    assert "按采集范围未收录 2 个" in render_fragment(tree)


# ---------------------------------------------------------------------------
# 四、已有库的收敛：默认只看不动，边一条不能少
# ---------------------------------------------------------------------------

def _seed_library(con):
    insert_process(con, "Biz.TI")
    insert_process(con, "}bedrock.cube.data.clear")
    con.execute("INSERT INTO cubes VALUES ('}Stats', '[]', '', FALSE, 0)")
    con.execute("INSERT INTO dimensions VALUES ('}Dimensions', TRUE, 0, '[]', '[]', '[]', '[]')")
    con.execute("INSERT INTO dimensions VALUES ('Region', FALSE, 2, '[]', '[]', '[]', '[]')")
    framework(con, "Biz.TI", "}bedrock.cube.data.clear")


def test_prune_dry_run_changes_nothing(con):
    from tm1_insight.store import scope_prune

    _seed_library(con)
    before = con.execute("SELECT count(*) FROM processes").fetchone()[0]
    result = scope_prune.prune(con, apply=False)

    assert result["applied"] is False
    assert result["objects"] == {"processes": 1, "cubes": 1, "dimensions": 1}
    assert result["object_total"] == 3
    assert result["referencing_edges"]["ti_framework_calls"] == 1
    assert con.execute("SELECT count(*) FROM processes").fetchone()[0] == before
    assert con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0] == 0


def test_prune_apply_moves_objects_and_keeps_edges(con):
    from tm1_insight.store import scope_prune

    _seed_library(con)
    result = scope_prune.prune(con, apply=True)

    assert result["applied"] and result["excluded"] == 3
    assert [r[0] for r in con.execute("SELECT name FROM processes").fetchall()] == ["Biz.TI"]
    assert [r[0] for r in con.execute("SELECT name FROM dimensions").fetchall()] == ["Region"]
    assert con.execute("SELECT count(*) FROM cubes").fetchone()[0] == 0
    # 边还在：删对象不等于删事实
    assert con.execute("SELECT count(*) FROM ti_framework_calls").fetchone()[0] == 1


def test_pruned_target_is_reported_as_not_collected(con):
    """收敛之后再读调用事实：目标应标成「按范围未收录」，不是「不存在」。"""
    from tm1_insight.store import scope_prune

    _seed_library(con)
    scope_prune.prune(con, apply=True)

    edge = calls.edges(con, caller="Biz.TI")[0]
    assert edge["kind"] == calls.KIND_FRAMEWORK
    assert edge["in_catalog"] is False

    tree = queries.process_call_tree(con, "Biz.TI", include_system=True)
    node = tree["callees"][0]
    assert node["catalog"] == "excluded"
    assert "未收录" in render_fragment(tree)


def test_prune_is_idempotent(con):
    from tm1_insight.store import scope_prune

    _seed_library(con)
    scope_prune.prune(con, apply=True)
    second = scope_prune.prune(con, apply=True)

    assert second["removed"] == {}
    assert second["excluded"] == 0
    assert con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0] == 3


# ---------------------------------------------------------------------------
# 五、端到端：列表页不能把「没收」说成「没有」
# ---------------------------------------------------------------------------

def test_process_list_reports_objects_outside_the_collection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import tm1_insight.config as config
    import tm1_insight.datasource as ds

    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "app")
    monkeypatch.setattr(config, "_DATA_DIR_OVERRIDE", None)
    monkeypatch.setattr(ds, "_source_cache", None)
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    config.get_settings.cache_clear()
    ds.load_demo_data()

    import duckdb as _duckdb

    with _duckdb.connect(str(config.get_settings().db_path)) as connection:
        connection.execute("DELETE FROM excluded_objects")
        for name in ("}bedrock.a", "}bedrock.b"):
            connection.execute(
                "INSERT INTO excluded_objects VALUES (?, 'processes', ?)", [name, EXCLUDED_REASON])

    from tm1_insight.api.app import app

    with TestClient(app) as client:
        page = client.get("/processes")
        assert page.status_code == 200
        # 对象表里没有它们（数量为 0），但页面仍要说清「另有 N 个未收录」
        assert "2 个系统对象按采集范围未收录" in page.text
        # 直接访问这些对象：不是 500，而是一个说得清的结果
        detail = client.get("/explorer/process/%7Dbedrock.a")
        assert detail.status_code in (404, 200)
    config.get_settings.cache_clear()
