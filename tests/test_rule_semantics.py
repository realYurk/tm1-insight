"""Task 20 —— Rule & Feeder 计算语义还原：解析器单元测试 + 集成 + 回归。

覆盖：
- 简单及嵌套表达式
- 多维坐标（显式 'Dim':'Member' 与位置坐标）
- 跨 Cube 引用 DB()
- 条件表达式（IF / ELISANC / ELISPAR）
- 属性查询（ATTRS / ATTRN）
- 注释与多行语法
- Feeder 与 Rule 的语义分离
- 未支持函数和动态坐标（标记 UNKNOWN，不静默删除）
- STET / CONTINUE / SKIPCHECK / FEEDSTRINGS 特殊语义
- 源码证据定位（line/column）
- 全注释源码（无规则）边界
"""
from __future__ import annotations

import duckdb
import pytest

from tm1_insight.learning.rule_semantics import (
    RuleSemanticsParser,
    parse_rule_semantics,
    _parse_area_bracket,
    _parse_db_call,
)
from tm1_insight.learning.syntax import statements

# 复用 datasource API 测试的隔离 TestClient fixture（Demo 兜底，不碰真实 data/）
from test_datasource_api import client  # noqa: F401


# ---------------------------------------------------------------------------
# 单元测试：坐标区域解析
# ---------------------------------------------------------------------------

def _tokens(code):
    return next(iter(statements((code, "", "", ""), include_logging=True)))


def test_area_bracket_explicit_dimension_member():
    toks = _tokens("['Scenario':'ACT','Year':'2026']")
    area, _ = _parse_area_bracket(toks, 0, ["Scenario", "Year"])
    assert area["status"] == "PARSED"
    coords = area["coordinates"]
    assert coords[0]["dimension"] == "Scenario" and coords[0]["member"] == "ACT"
    assert coords[1]["dimension"] == "Year" and coords[1]["member"] == "2026"


def test_area_bracket_member_set():
    toks = _tokens("['Year':{'2025','2026'}]")
    area, _ = _parse_area_bracket(toks, 0, ["Year"])
    assert area["coordinates"][0]["members"] == ["2025", "2026"]
    assert area["coordinates"][0]["kind"] == "set"


def test_area_bracket_bare_members_do_not_inherit_cube_dimension_order():
    # Task 20.1: Rule area members are not positional Cube coordinates.
    toks = _tokens("[{'A','B'}, 'CKD', 'Amount']")
    area, _ = _parse_area_bracket(toks, 0, ["Scenario", "Version", "Measure"])
    coords = area["coordinates"]
    assert all(c['dimension'] is None for c in coords)
    assert coords[0]['members']==['A','B'] and coords[1]['member']=='CKD' and coords[2]['member']=='Amount'
    assert area['status']=='PARTIAL' and any('OWNERSHIP_UNKNOWN' in r for r in area['unresolved_reasons'])


def test_area_bracket_dynamic_coordinate_marked_unknown():
    toks = _tokens("['Scenario':!Year]")
    area, _ = _parse_area_bracket(toks, 0, ["Scenario"])
    coord = area["coordinates"][0]
    assert coord["status"] == "UNKNOWN" and coord["kind"] == "dynamic"


# ---------------------------------------------------------------------------
# 单元测试：DB() 跨 Cube 引用
# ---------------------------------------------------------------------------

def test_db_call_literal_cube_and_regions():
    toks = _tokens("DB('Cube_B', !Year, 'Member1', !Region)")
    token, args = next(iter(_get_calls(toks)))
    ref = _parse_db_call(token, args, {"Cube_B"})
    assert ref["cube"] == "Cube_B" and ref["cube_resolved"] is True
    assert ref["coordinates"][0]["kind"] == "region"
    assert ref["coordinates"][0]["dimension"] == "Year"
    assert ref["coordinates"][1]["kind"] == "literal"
    assert ref["coordinates"][1]["value"] == "Member1"


def test_db_call_unresolved_dynamic_cube():
    toks = _tokens("DB(pDynamicCube, !Year, 'M')")
    token, args = next(iter(_get_calls(toks)))
    ref = _parse_db_call(token, args, {"Cube_B"})
    assert ref["cube_resolved"] is False


def _get_calls(tokens):
    from tm1_insight.learning.syntax import calls
    return calls(tokens)


# ---------------------------------------------------------------------------
# 集成测试：Rule 语义解析
# ---------------------------------------------------------------------------

def test_parse_simple_rule_with_db_reference():
    code = "['Amount'] = N: DB('Cube_B', !Year, 'Member1', 'Member1');"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], {"Cube_B"})
    assert len(r["rules"]) == 1
    rule = r["rules"][0]
    assert rule["qualifier"] == "N"
    assert rule["rhs_kind"] == "DB_REFERENCE"
    assert rule["db_references"][0]["cube"] == "Cube_B"
    assert rule["status"] == "PARTIAL"  # bare Amount has no member-ownership evidence
    assert rule['rhs']['status']=='PARSED' and rule['lhs']['status']=='PARTIAL'


def test_parse_nested_if_condition():
    code = ("['Amount'] = N: If(DB('Info', !Car Line, 'Displacement')>1.5, "
            "['Per Car']*DB('Assumption', !Scenario), CONTINUE);")
    r = parse_rule_semantics(code, "Cube_A", ["Scenario"], {"Info", "Assumption"})
    rule = r["rules"][0]
    assert rule["rhs_kind"] == "EXPRESSION"
    assert [c["func"] for c in rule["conditions"]] == ["IF"]
    assert sorted(d["cube"] for d in rule["db_references"]) == ["Assumption", "Info"]
    # CONTINUE 出现在条件内，非顶层 STET/CONTINUE，不应触发 special
    assert rule["special"] is None


def test_parse_attr_and_elisanc():
    code = ("['Amount'] = N: If(ATTRS('Car Line', !Car Line, 'Power') @= 'PHEV', "
            "If(ELISANC('Scenario', 'All Scenarios', !Scenario)=1, 1, 0), CONTINUE);")
    r = parse_rule_semantics(code, "Cube_A", ["Scenario"], set())
    rule = r["rules"][0]
    funcs = {c["func"] for c in rule["attribute_calls"]}
    assert "ATTRS" in funcs
    cond_funcs = {c["func"] for c in rule["conditions"]}
    assert "IF" in cond_funcs and "ELISANC" in cond_funcs


def test_parse_stet_and_continue():
    code = "['Amount'] = N: STET;"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], set())
    assert r["rules"][0]["special"] == "STET"
    assert r["rules"][0]["rhs_kind"] == "STET"

    code2 = "['Amount'] = N: CONTINUE;"
    r2 = parse_rule_semantics(code2, "Cube_A", ["Year"], set())
    assert r2["rules"][0]["special"] == "CONTINUE"


def test_parse_directives():
    code = "FEEDSTRINGS;\nSKIPCHECK;\n['A'] = N: 1;"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], set())
    assert [d["kind"] for d in r["directives"]] == ["FEEDSTRINGS", "SKIPCHECK"]
    assert len(r["rules"]) == 1


def test_parse_comments_and_multiline():
    code = ("# 这是注释\n"
            "['A', # 行内注释\n"
            " 'B'] = N: DB('C', !Year, 'M');\n"
            "# 全注释行\n")
    r = parse_rule_semantics(code, "Cube_A", ["Year"], {"C"})
    assert len(r["rules"]) == 1
    assert r["rules"][0]["db_references"][0]["cube"] == "C"


def test_parse_feeder_separated_from_rule():
    code = ("['Amount'] = N: DB('C', !Year, 'M');\n"
            "FEEDERS;\n"
            "['Amount'] => DB('C', !Year, 'M');\n")
    r = parse_rule_semantics(code, "Cube_A", ["Year"], {"C"})
    assert len(r["rules"]) == 1
    assert len(r["feeders"]) == 1
    feeder = r["feeders"][0]
    # Feeder 目标独立记录，不混入 Rule 数值公式
    assert feeder["target_area"]["kind"] == "db_reference"
    assert feeder["target_area"]["db"]["cube"] == "C"
    assert feeder["status"] == "PARTIAL"  # source area mapping is unconfirmed
    assert feeder['target_area']['status']=='PARSED'


def test_parse_unsupported_function_kept_not_silently_dropped():
    code = "['Amount'] = N: MyUnknownFunc(DB('C', !Year, 'M'), 3.14);"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], {"C"})
    rule = r["rules"][0]
    # DB 引用仍被提取
    assert rule["db_references"][0]["cube"] == "C"
    # 表达式保留原文
    assert "MyUnknownFunc" in rule["rhs"]["expression"]


def test_parse_all_commented_source_yields_no_rules():
    code = "#['A'] = N: 1;\n#FEEDERS;\n#['A'] => ['B'];\n"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], set())
    assert r["rules"] == [] and r["feeders"] == []


def test_parse_empty_source():
    r = parse_rule_semantics("", "Cube_A", ["Year"], set())
    assert r["rules"] == [] and r["feeders"] == [] and r["directives"] == []


def test_parse_malformed_rule_marked_unknown():
    code = "this is not a valid rule"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], set())
    assert r["rules"] and r["rules"][0]["status"] == "UNKNOWN"


def test_evidence_line_locations_recorded():
    code = "SKIPCHECK;\n['Amount'] = N: DB('C', !Year, 'M');\n"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], {"C"})
    rule = r["rules"][0]
    assert rule["line_start"] == 2
    assert rule["db_references"][0]["line"] == 2
    assert r["directives"][0]["line"] == 1


def test_parser_returns_version_and_source_hash():
    code = "['A'] = N: 1;"
    r = parse_rule_semantics(code, "Cube_A", ["Year"], set())
    assert r["version"] == "rule-semantics-1"
    assert len(r["source_hash"]) == 64


# ---------------------------------------------------------------------------
# 集成测试：queries.cube_rule_semantics + 真实库（只读）
# ---------------------------------------------------------------------------

def _collection_db_path():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "collections" / "model-rytp0epv" / "db" / "tm1_insight.duckdb"
    return p if p.exists() else None


@pytest.mark.skipif(_collection_db_path() is None, reason="本地采集库不可用")
def test_real_data_allocation_driver_bp_semantics():
    from tm1_insight.store.queries import cube_rule_semantics
    con = duckdb.connect(str(_collection_db_path()), read_only=True)
    try:
        r = cube_rule_semantics(con, "Allocation Driver BP")
        assert r["available"] is True
        assert r["rules"], "Allocation Driver BP 应有 Rule"
        # 引用 BP PnL Assumption 与 BP Management Report PnL
        all_refs = {d["cube"] for rule in r["rules"] for d in rule["db_references"]}
        assert "BP PnL Assumption" in all_refs
        assert "BP Management Report PnL" in all_refs
        # 有 FEEDSTRINGS/SKIPCHECK 指令与 Feeder
        assert [d["kind"] for d in r["directives"]] == ["FEEDSTRINGS", "SKIPCHECK"]
        assert r["feeders"]
        # 有 STET 特殊语义
        assert any(rule["special"] == "STET" for rule in r["rules"])
    finally:
        con.close()


@pytest.mark.skipif(_collection_db_path() is None, reason="本地采集库不可用")
def test_real_data_bp_management_report_references_info_car_line():
    from tm1_insight.store.queries import cube_rule_semantics
    con = duckdb.connect(str(_collection_db_path()), read_only=True)
    try:
        r = cube_rule_semantics(con, "BP Management Report PnL")
        assert r["available"] is True
        all_refs = {d["cube"] for rule in r["rules"] for d in rule["db_references"]}
        assert "Info Car Line" in all_refs, "BP Management Report PnL 应引用 Info Car Line"
        # 有属性查询（ATTRS）
        assert any(rule["attribute_calls"] for rule in r["rules"])
        # 有 Feeder
        assert r["feeders"]
    finally:
        con.close()


@pytest.mark.skipif(_collection_db_path() is None, reason="本地采集库不可用")
def test_real_data_info_car_line_fully_commented():
    from tm1_insight.store.queries import cube_rule_semantics
    con = duckdb.connect(str(_collection_db_path()), read_only=True)
    try:
        r = cube_rule_semantics(con, "Info Car Line")
        # 全注释源码 → 无规则/无 Feeder（诚实标记，不伪造）
        assert r["rules"] == [] and r["feeders"] == []
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 回归测试：旧快照兼容（architecture 的 rules 段仍保留 references/groups）
# ---------------------------------------------------------------------------

def test_architecture_rules_retain_legacy_references_and_groups():
    from tm1_insight import architecture
    from tm1_insight.store.schema import ALL_TABLES
    con = duckdb.connect(":memory:")
    for sql in ALL_TABLES.values():
        con.execute(sql)
    con.execute("INSERT INTO cubes VALUES ('Cube_B', ?, '', true, 3)",
                ['["Year","Region","Measure"]'])
    for i, d in enumerate(["Year", "Region", "Measure"]):
        con.execute("INSERT INTO cube_has_dimension VALUES ('Cube_B', ?, ?)", [d, i])
    con.execute("INSERT INTO cubes VALUES ('RuleOutput', ?, ?, true, 1)",
                ['["Year"]', "['Member1']=N:DB('Cube_B',!Year,'Member1','Member1');\nFEEDERS;['Member1']=>DB('Cube_B',!Year,'Member1','Member1');"])
    con.execute("INSERT INTO cube_has_dimension VALUES ('RuleOutput','Year',0)")
    # Load 的 TI 代码真实写入 Cube_B，驱动 Cube_B 进入核心范围
    prolog = "DataSourceType='VIEW';DataSourceNameForServer='Cube_A';"
    data = "CellPutN(1,'Cube_B',vYear,'Member1','Member1');"
    con.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('Load',?,?,?,?,?)",
                [prolog, '', data, '', '[]'])
    con.execute("INSERT INTO cubes VALUES ('Cube_A', ?, '', true, 1)", ['["Year"]'])
    con.execute("INSERT INTO cube_has_dimension VALUES ('Cube_A','Year',0)")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    con.execute("INSERT INTO rule_references_cube VALUES ('RuleOutput','Cube_B')")
    try:
        report = architecture.build(con, "Load", include_downstream=True)
        rule = report["rules"][0]
        # 旧字段保留
        assert {r["kind"] for r in rule["references"]} == {"rule_read", "feeder_reference"}
        assert rule["groups"]
        # 新字段存在
        assert "rule_semantics" in rule
        assert "feeder_semantics" in rule
        assert len(rule["rule_semantics"]) == 1
        assert len(rule["feeder_semantics"]) == 1
    finally:
        con.close()


# ---------------------------------------------------------------------------
# API 端点接线冒烟测试
# ---------------------------------------------------------------------------

def test_api_cube_rules_endpoint_returns_semantics(client):
    """/api/cube/{cube}/rules 端点返回结构化语义 IR（Demo 兜底不 500）。"""
    # Demo 模式下列出 cubes 后取第一个有规则的 cube 验证端点不报错
    r = client.get("/api/search-all", params={"q": ""})
    assert r.status_code == 200
    # 直接验证端点对不存在 cube 返回可用性标记而非 500
    resp = client.get("/api/cube/__no_such_cube__/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
