"""业务架构（business-map）：模型级事实的契约测试。

自建一个极小的内存库，只放这个模块关心的表，
避免和其它测试的 fixture 详情耦合。
"""
from __future__ import annotations

import duckdb
import pytest

from tm1_insight import business_map
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    for sql in ALL_TABLES.values():
        c.execute(sql)
    yield c
    c.close()


def add_cube(con, name, rules=""):
    con.execute("INSERT INTO cubes VALUES (?,?,?,?,?)",
                [name, "[]", rules, bool(rules), 0])


def add_flow(con, process, target, sources):
    con.execute("INSERT INTO ti_flows VALUES (?,?,?,1)", [process, target, sources])


def edges(*pairs):
    return [{"source": a, "target": b, "processes": ["Load"]} for a, b in pairs]


# ---- 纯函数：链、枢纽、两端 ----

def test_longest_chain_follows_the_dag():
    chain = business_map.longest_chain(edges(("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")))
    assert chain["length"] == 3
    assert chain["path"] == ["A", "B", "C", "D"]
    assert [h["to"] for h in chain["hops"]] == ["B", "C", "D"]


def test_cycle_does_not_hang_and_is_counted():
    chain = business_map.longest_chain(edges(("A", "B"), ("B", "C"), ("C", "B"), ("C", "D")))
    assert chain["length"] >= 2
    assert chain["cyclic"] == 2  # B、C 互相依赖，不进 DAG 距离
    assert len(set(chain["path"])) == len(chain["path"])  # 链内不重复


def test_single_edge_and_empty_graph_are_safe():
    assert business_map.longest_chain([]) == {"length": 0, "path": [], "hops": [], "cyclic": 0}
    one = business_map.longest_chain(edges(("A", "B")))
    assert one["length"] == 1 and one["path"] == ["A", "B"]


def test_top_chains_use_distinct_starts_and_skip_short_paths():
    graph = edges(("A", "B"), ("B", "C"), ("C", "D"), ("X", "Y"), ("Y", "Z"), ("P", "Q"))
    chains = business_map.top_chains(graph, limit=3)
    assert [c["length"] for c in chains] == [3, 2]
    assert [c["path"][0] for c in chains] == ["A", "X"]  # 同一长链不会被切成多条


def test_hubs_rank_by_downstream_then_upstream():
    rows = business_map.hubs(edges(("A", "C"), ("B", "C"), ("C", "D"), ("A", "B")), limit=2)
    assert rows[0] == {"name": "A", "downstream": 2, "upstream": 0}
    assert rows[1]["name"] == "C" and rows[1]["upstream"] == 2


def test_ends_count_only_one_sided_objects():
    assert business_map.ends(edges(("A", "B"), ("B", "C"), ("X", "C"))) == {"starts": 2, "ends": 1}


# ---- 事实读取：系统对象、自环、拼串名字都不进业务版图 ----

def test_build_edges_filters_system_self_and_unknown(con):
    for name in ("Cube_A", "Cube_B", "}Control"):
        add_cube(con, name)
    add_flow(con, "Load", "Cube_B", '["Cube_A"]')                       # 正常
    add_flow(con, "Self", "Cube_B", '["Cube_B"]')                       # 自环
    add_flow(con, "Sys", "}Control", '["Cube_A"]')                      # 系统对象
    add_flow(con, "Ghost", "Cube_B", '["Payment \' | pX | \' Input"]')  # 源码拼串，不是对象
    built = business_map.build_edges(con)
    assert [(e["source"], e["target"], e["processes"]) for e in built] == [
        ("Cube_A", "Cube_B", ["Load"])
    ]


def test_build_edges_merges_case_variants(con):
    add_cube(con, "Cube_A")
    add_cube(con, "Cube_B")
    add_flow(con, "Load", "Cube_B", '["Cube_A"]')
    add_flow(con, "Load2", "cube_b", '["cube_a"]')
    built = business_map.build_edges(con)
    assert len(built) == 1
    assert built[0]["target"] == "Cube_B"
    assert built[0]["processes"] == ["Load", "Load2"]


def test_overview_reports_rule_only_and_no_source(con):
    add_cube(con, "Loader")
    add_cube(con, "Calc", "SKIPCHECK;\n['A']=N:1;")
    add_cube(con, "Manual")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Loader')")
    data = business_map.overview(con)
    assert data["totals"]["cubes"] == 3
    assert data["totals"]["writers"] == 1
    assert data["rule_only"] == 1
    assert data["no_source"] == 1
    assert data["edges"] == 0
    assert "3 个业务 Cube" in business_map.headline(data)


def test_scheduled_cubes_follows_one_level_of_child_calls(con):
    add_cube(con, "Loader")
    con.execute("INSERT INTO processes(name) VALUES ('Wrapper')")
    con.execute("INSERT INTO processes(name) VALUES ('Worker')")
    con.execute("INSERT INTO processes(name) VALUES ('Manual_Only')")
    con.execute("INSERT INTO chores(name,processes,process_count) VALUES ('Nightly','[\"Wrapper\"]',1)")
    con.execute("INSERT INTO chore_runs_process VALUES ('Nightly','Wrapper',0)")
    con.execute("INSERT INTO ti_business_calls VALUES ('Wrapper','Worker','[]')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Worker','Loader')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Manual_Only','Loader')")
    data = business_map.overview(con)
    assert data["totals"]["chores"] == 1
    assert data["scheduled_cubes"] == 1  # 壳 TI 调用的子过程才算覆盖


def test_empty_payload_keeps_the_same_shape(con):
    empty = business_map.empty()
    assert empty["schema"] == business_map.SCHEMA
    assert empty["totals"]["cubes"] == 0
    assert business_map.headline(empty) == "当前数据源没有可用的 Cube 事实。"
    # 空库上跑一遍，键必须与空结构一致，页面不会因为缺字段报错。
    assert set(business_map.overview(con)) == set(empty)
