"""血缘页的服务端事实：结论句、大小写身份、起点列表。"""
from __future__ import annotations

import duckdb
import pytest

from tm1_insight.store import queries
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    for sql in ALL_TABLES.values():
        c.execute(sql)
    yield c
    c.close()


def add_cube(con, name, rules=""):
    con.execute("INSERT INTO cubes VALUES (?,?,?,?,?)", [name, "[]", rules, bool(rules), 0])


def test_verdict_prefers_writers_then_rule_then_nothing(con):
    add_cube(con, "Loaded", "['A']=N:1;")
    add_cube(con, "Calc", "['A']=N:DB('Upstream',!Year);")
    add_cube(con, "Rolling", "['A']=N:DB('Rolling',!Year);")
    add_cube(con, "Manual")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Loaded')")
    con.execute("INSERT INTO rule_references_cube VALUES ('Calc','Upstream')")
    con.execute("INSERT INTO rule_references_cube VALUES ('Rolling','Rolling')")

    loaded = queries.lineage_facts(con, "Loaded")
    assert "1 个 TI 写入" in loaded["verdict"] and "Rule" in loaded["verdict"]

    calc = queries.lineage_facts(con, "Calc")
    assert calc["rule_sources"] == ["Upstream"]
    assert "Rule 从 1 个其它 Cube 计算" in calc["verdict"]

    rolling = queries.lineage_facts(con, "Rolling")
    assert rolling["rule_self_refs"] == 1 and rolling["rule_sources"] == []
    assert "只引用自己" in rolling["verdict"]
    # 自引用要能解释「为什么画布是空的」
    assert "滚动计算" in rolling["reason"]

    manual = queries.lineage_facts(con, "Manual")
    assert manual["writers"] == 0 and not manual["has_rule"]
    assert "前端录入" in manual["verdict"]


def test_lookup_is_case_insensitive_and_returns_canonical_name(con):
    add_cube(con, "BP PnL Assumption", "['A']=N:1;")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','bp pnl assumption')")
    facts = queries.lineage_facts(con, "bp pnl assumption")
    assert facts["found"] and facts["display"] == "BP PnL Assumption"
    assert facts["writers"] == 1


def test_missing_cube_is_reported_not_invented(con):
    facts = queries.lineage_facts(con, "No Such Cube")
    assert facts["found"] is False
    assert facts["writers"] == 0 and facts["verdict"] == ""
    assert "没有这个对象" in facts["next_step"]


def test_starters_skip_system_objects_and_rank_by_traffic(con):
    add_cube(con, "Busy")
    add_cube(con, "Quiet")
    add_cube(con, "}Control")
    for i in range(3):
        con.execute("INSERT INTO process_writes_cube VALUES (?, 'Busy')", [f"W{i}"])
    con.execute("INSERT INTO process_reads_cube VALUES ('Loader','Busy')")
    con.execute("INSERT INTO process_writes_cube VALUES ('W0','Quiet')")
    con.execute("INSERT INTO process_reads_cube VALUES ('Loader','}Control')")
    starters = queries.lineage_starters(con, 5)
    assert [s["name"] for s in starters] == ["Busy", "Quiet"]
    assert starters[0] == {"name": "Busy", "writers": 3, "readers": 1}
