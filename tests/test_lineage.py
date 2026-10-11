"""Lineage Engine v1（lineage/）的回归测试。

覆盖（对应 Task 12 要求）：
1.  单跳 A → B
2.  两跳 A → B → C（得到 A → C）
3.  三跳 A → B → C → D
4.  多路径 A→B、A→C、B→D、C→D
5.  Cycle A→B→C→A（不死循环、不爆栈、稳定）
6.  Self dependency A→A
7.  Disconnected graph（A→B 与 C→D 互不相连）
8.  Determinism（不同输入顺序 → 相同 Lineage）
9.  Depth（direct=1，transitive 递增）
10. Path / explainability（A→D 可追溯 A→B→C→D）
11. Multiple paths 不产生重复 Lineage
12. 依赖契约回归（Dependency = direct，Lineage = transitive）

所有测试走真实链路：Dependency → Lineage Engine，不 mock。
测试数据均为最小匿名片段。
"""
from __future__ import annotations

from tm1_insight.domain.model import Dependency, DependencyKind
from tm1_insight.lineage import (
    LineageEngine,
    build_lineage,
    get_downstream,
    get_upstream,
)


def _dep(kind: DependencyKind, source: str, target: str) -> Dependency:
    return Dependency(kind=kind, source=source, target=target)


# ---------------------------------------------------------------------------
# 1. 单跳
# ---------------------------------------------------------------------------
def test_single_hop():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    lins = build_lineage(deps)

    pairs = {(l.source, l.target) for l in lins}
    assert ("A", "B") in pairs
    # 单跳只产一条
    assert len(lins) == 1
    assert lins[0].depth == 1
    assert lins[0].path == ("A", "B")


# ---------------------------------------------------------------------------
# 2. 两跳
# ---------------------------------------------------------------------------
def test_two_hop():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
    ]
    lins = build_lineage(deps)

    pairs = {(l.source, l.target) for l in lins}
    assert ("A", "B") in pairs   # direct
    assert ("B", "C") in pairs   # direct
    assert ("A", "C") in pairs   # transitive（两跳）

    ac = next(l for l in lins if l.source == "A" and l.target == "C")
    assert ac.depth == 2
    assert ac.path == ("A", "B", "C")


# ---------------------------------------------------------------------------
# 3. 三跳
# ---------------------------------------------------------------------------
def test_three_hop():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)

    ad = next(l for l in lins if l.source == "A" and l.target == "D")
    assert ad.depth == 3
    assert ad.path == ("A", "B", "C", "D")


# ---------------------------------------------------------------------------
# 4. 多路径
# ---------------------------------------------------------------------------
def test_multiple_paths():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "D"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)

    # A → D 有两条路径（A→B→D 与 A→C→D），但只保留一条 Lineage
    ad = [l for l in lins if l.source == "A" and l.target == "D"]
    assert len(ad) == 1
    assert ad[0].depth == 2
    # 字典序最小的路径（B < C）
    assert ad[0].path == ("A", "B", "D")


# ---------------------------------------------------------------------------
# 5. Cycle
# ---------------------------------------------------------------------------
def test_cycle_safe():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "A"),
    ]
    lins = build_lineage(deps)

    # 不死循环、不爆栈，结果有限且确定
    pairs = {(l.source, l.target) for l in lins}
    assert ("A", "B") in pairs
    assert ("A", "C") in pairs   # A→B→C
    assert ("B", "A") in pairs   # B→C→A
    assert ("B", "C") in pairs
    assert ("C", "A") in pairs
    assert ("C", "B") in pairs   # C→A→B
    # 无 A→A（环回到自身被 path 内去重挡住）
    assert ("A", "A") not in pairs


# ---------------------------------------------------------------------------
# 6. Self dependency
# ---------------------------------------------------------------------------
def test_self_dependency():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "A")]
    lins = build_lineage(deps)

    pairs = {(l.source, l.target) for l in lins}
    # self 边作为 direct（depth=1）保留，不静默丢弃，也不死循环
    assert ("A", "A") in pairs
    self_lin = next(l for l in lins if l.source == "A" and l.target == "A")
    assert self_lin.depth == 1


# ---------------------------------------------------------------------------
# 7. Disconnected graph
# ---------------------------------------------------------------------------
def test_disconnected_graph():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)

    pairs = {(l.source, l.target) for l in lins}
    assert ("A", "B") in pairs
    assert ("C", "D") in pairs
    # 不能产生跨连通分量的虚假关系
    assert ("A", "C") not in pairs
    assert ("A", "D") not in pairs
    assert ("C", "B") not in pairs


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------
def test_determinism():
    deps_forward = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "D"),
    ]
    deps_reverse = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "D"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
    ]

    r1 = build_lineage(deps_forward)
    r2 = build_lineage(deps_reverse)

    # 内容一致 + 顺序一致
    assert [(l.source, l.target, l.depth) for l in r1] == \
        [(l.source, l.target, l.depth) for l in r2]


# ---------------------------------------------------------------------------
# 9. Depth 定义锁定
# ---------------------------------------------------------------------------
def test_depth_definition():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)
    by_pair = {(l.source, l.target): l.depth for l in lins}

    assert by_pair[("A", "B")] == 1   # direct
    assert by_pair[("A", "C")] == 2
    assert by_pair[("A", "D")] == 3
    assert by_pair[("B", "C")] == 1
    assert by_pair[("B", "D")] == 2


# ---------------------------------------------------------------------------
# 10. Path / explainability
# ---------------------------------------------------------------------------
def test_path_explainability():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)

    ad = next(l for l in lins if l.source == "A" and l.target == "D")
    # 能追溯完整路径
    assert ad.path == ("A", "B", "C", "D")
    # 支撑路径的直接依赖数 = 跳数
    assert len(ad.dependencies) == 3
    assert ad.dependencies[0].target == "B"
    assert ad.dependencies[1].target == "C"
    assert ad.dependencies[2].target == "D"


# ---------------------------------------------------------------------------
# 11. Multiple paths 不重复
# ---------------------------------------------------------------------------
def test_multiple_paths_no_duplicate():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "D"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    lins = build_lineage(deps)

    # 每个 (source, target) 只出现一次
    keys = [(l.source, l.target) for l in lins]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# 12. TM1 实际场景：Process 调用链 → cube 血缘
# ---------------------------------------------------------------------------
def test_tm1_process_to_cube_lineage():
    # Process_A CALLS Process_B；Process_B WRITES Cube_C
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "Process_A", "Process_B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "Process_B", "Cube_C"),
    ]
    lins = build_lineage(deps)

    pairs = {(l.source, l.target) for l in lins}
    assert ("Process_A", "Process_B") in pairs      # direct
    assert ("Process_B", "Cube_C") in pairs          # direct
    assert ("Process_A", "Cube_C") in pairs          # transitive（Lineage）

    ac = next(l for l in lins if l.source == "Process_A" and l.target == "Cube_C")
    assert ac.depth == 2
    assert ac.path == ("Process_A", "Process_B", "Cube_C")


# ---------------------------------------------------------------------------
# 附加：Query API（upstream / downstream）
# ---------------------------------------------------------------------------
def test_downstream_api():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
    ]
    downstream = get_downstream(deps, "A")
    pairs = {(l.source, l.target) for l in downstream}
    assert ("A", "B") in pairs
    assert ("A", "C") in pairs
    # 不含反向
    assert not any(l.source != "A" for l in downstream)


def test_upstream_api():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
    ]
    upstream = get_upstream(deps, "C")
    pairs = {(l.source, l.target) for l in upstream}
    # 上游关系保持 source → target 方向：A→C、B→C
    assert ("A", "C") in pairs
    assert ("B", "C") in pairs


def test_downstream_empty_for_unknown_source():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    assert get_downstream(deps, "Z") == []


# ---------------------------------------------------------------------------
# 附加：Lineage Engine 不依赖 DuckDB / NetworkX / Neo4j / parser / resolver
# ---------------------------------------------------------------------------
def test_lineage_module_has_no_forbidden_dependency():
    import ast
    import tm1_insight.lineage.engine as le

    with open(le.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy", "networkx", "neo4j"}
    forbidden_modules = {"tm1_insight.ingest", "tm1_insight.store", "tm1_insight.api",
                         "tm1_insight.parser", "tm1_insight.resolver"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            assert not mod.startswith("tm1_insight.ingest"), "engine 不应依赖 ingest（不重新解析 TI）"
            assert not mod.startswith("tm1_insight.parser"), "engine 不应依赖 parser"
            assert not mod.startswith("tm1_insight.resolver"), "engine 不应依赖 resolver"


def test_lineage_engine_class_api():
    engine = LineageEngine()
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    lins = engine.build_lineage(deps)
    assert len(lins) == 1
    assert lins[0].source == "A" and lins[0].target == "B"
