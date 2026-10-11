"""Impact Analysis Engine v1（impact/）的测试。

覆盖（对应 Task 13 要求）：
1.  empty dependency
2.  single direct impact
3.  two-hop indirect impact
4.  three-hop impact
5.  direct + indirect classification
6.  deterministic result
7.  reversed dependency input
8.  cycle
9.  self dependency
10. disconnected graph
11. multiple paths
12. path preservation
13. depth preservation
14. dependency evidence preservation
15. Process → Process → Cube
16. Rule → Cube
17. unknown source
18. duplicate dependencies
19. no Graph DB dependency
20. regression with existing tests

所有测试走真实链路：Dependency → Lineage → Impact，不 mock。
测试数据均为最小匿名片段。
"""
from __future__ import annotations

from tm1_insight.domain.model import Dependency, DependencyKind, ImpactKind
from tm1_insight.impact import ImpactEngine, analyze_impact, get_impact


def _dep(kind: DependencyKind, source: str, target: str) -> Dependency:
    return Dependency(kind=kind, source=source, target=target)


# ---------------------------------------------------------------------------
# 1. empty dependency
# ---------------------------------------------------------------------------
def test_empty_dependency():
    assert analyze_impact([], "A") == []


# ---------------------------------------------------------------------------
# 2. single direct impact
# ---------------------------------------------------------------------------
def test_single_direct_impact():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    impacts = analyze_impact(deps, "A")

    assert len(impacts) == 1
    imp = impacts[0]
    assert imp.source == "A"
    assert imp.target == "B"
    assert imp.kind == ImpactKind.DIRECT
    assert imp.depth == 1
    assert imp.path == ("A", "B")


# ---------------------------------------------------------------------------
# 3. two-hop indirect impact
# ---------------------------------------------------------------------------
def test_two_hop_indirect_impact():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
    ]
    impacts = analyze_impact(deps, "A")

    by_target = {imp.target: imp for imp in impacts}
    assert set(by_target) == {"B", "C"}

    assert by_target["B"].kind == ImpactKind.DIRECT
    assert by_target["B"].depth == 1

    assert by_target["C"].kind == ImpactKind.INDIRECT
    assert by_target["C"].depth == 2
    assert by_target["C"].path == ("A", "B", "C")


# ---------------------------------------------------------------------------
# 4. three-hop impact
# ---------------------------------------------------------------------------
def test_three_hop_impact():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    by_target = {imp.target: imp for imp in impacts}
    assert by_target["D"].kind == ImpactKind.INDIRECT
    assert by_target["D"].depth == 3
    assert by_target["D"].path == ("A", "B", "C", "D")


# ---------------------------------------------------------------------------
# 5. direct + indirect classification（depth 一一对应）
# ---------------------------------------------------------------------------
def test_direct_indirect_classification():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    for imp in impacts:
        if imp.kind == ImpactKind.DIRECT:
            assert imp.depth == 1
        else:
            assert imp.kind == ImpactKind.INDIRECT
            assert imp.depth >= 2

    # 明确分类：B direct；C/D indirect
    kinds = {imp.target: imp.kind for imp in impacts}
    assert kinds["B"] == ImpactKind.DIRECT
    assert kinds["C"] == ImpactKind.INDIRECT
    assert kinds["D"] == ImpactKind.INDIRECT


# ---------------------------------------------------------------------------
# 6 + 7. deterministic result + reversed dependency input
# ---------------------------------------------------------------------------
def test_deterministic_ordering():
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

    r1 = analyze_impact(deps_forward, "A")
    r2 = analyze_impact(deps_reverse, "A")

    # 内容与顺序完全一致（depth 升序 → target 字典序）
    assert [(i.target, i.kind, i.depth) for i in r1] == \
        [(i.target, i.kind, i.depth) for i in r2]


# ---------------------------------------------------------------------------
# 8. cycle（不死循环、不爆栈、不重复、deterministic）
# ---------------------------------------------------------------------------
def test_cycle_safe():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "A"),
    ]
    impacts = analyze_impact(deps, "A")

    targets = [i.target for i in impacts]
    # 每个 target 只出现一次
    assert len(targets) == len(set(targets))
    # A 的下游：B（direct）、C（indirect，A→B→C）
    assert set(targets) == {"B", "C"}
    # 不产生 A → A（环回到自身被 path 内去重挡住，遵循 Lineage 既有语义）
    assert "A" not in targets


# ---------------------------------------------------------------------------
# 9. self dependency（遵循 Lineage 既有语义，不擅自删除）
# ---------------------------------------------------------------------------
def test_self_dependency():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "A")]
    impacts = analyze_impact(deps, "A")

    # self 边作为 direct（depth=1）保留，与 Lineage 语义一致
    assert len(impacts) == 1
    assert impacts[0].target == "A"
    assert impacts[0].kind == ImpactKind.DIRECT
    assert impacts[0].depth == 1


# ---------------------------------------------------------------------------
# 10. disconnected graph（不产生跨连通分量的虚假影响）
# ---------------------------------------------------------------------------
def test_disconnected_graph():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    targets = {i.target for i in impacts}
    assert targets == {"B"}
    assert "D" not in targets


# ---------------------------------------------------------------------------
# 11. multiple paths（只保留 Lineage 提供的一条 deterministic path）
# ---------------------------------------------------------------------------
def test_multiple_paths():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "D"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    d_impacts = [i for i in impacts if i.target == "D"]
    # D 只保留一条 path（Lineage v1 语义：字典序最小，A→B→D）
    assert len(d_impacts) == 1
    assert d_impacts[0].path == ("A", "B", "D")
    assert d_impacts[0].depth == 2


# ---------------------------------------------------------------------------
# 12. path preservation（可解释性）
# ---------------------------------------------------------------------------
def test_path_preservation():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    d_imp = next(i for i in impacts if i.target == "D")
    assert d_imp.path == ("A", "B", "C", "D")


# ---------------------------------------------------------------------------
# 13. depth preservation
# ---------------------------------------------------------------------------
def test_depth_preservation():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "B", "C"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "C", "D"),
    ]
    impacts = analyze_impact(deps, "A")

    by_target = {i.target: i.depth for i in impacts}
    assert by_target["B"] == 1
    assert by_target["C"] == 2
    assert by_target["D"] == 3


# ---------------------------------------------------------------------------
# 14. dependency evidence preservation（支撑路径的直接依赖）
# ---------------------------------------------------------------------------
def test_dependency_evidence_preservation():
    dep_ab = _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")
    dep_bc = _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C")
    deps = [dep_ab, dep_bc]
    impacts = analyze_impact(deps, "A")

    c_imp = next(i for i in impacts if i.target == "C")
    # 间接影响的 dependencies 保留整条路径的直接依赖（A→B 与 B→C）
    assert len(c_imp.dependencies) == 2
    assert c_imp.dependencies[0].source == "A"
    assert c_imp.dependencies[0].target == "B"
    assert c_imp.dependencies[1].source == "B"
    assert c_imp.dependencies[1].target == "C"

    # direct 影响的 dependencies 保留单条直接依赖
    b_imp = next(i for i in impacts if i.target == "B")
    assert len(b_imp.dependencies) == 1
    assert b_imp.dependencies[0].source == "A"
    assert b_imp.dependencies[0].target == "B"


# ---------------------------------------------------------------------------
# 15. TM1 场景：Process → Process → Cube
# ---------------------------------------------------------------------------
def test_process_process_cube():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "Process_A", "Process_B"),
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "Process_B", "Cube_C"),
    ]
    impacts = analyze_impact(deps, "Process_A")

    by_target = {i.target: i for i in impacts}
    assert by_target["Process_B"].kind == ImpactKind.DIRECT
    assert by_target["Process_B"].depth == 1
    assert by_target["Cube_C"].kind == ImpactKind.INDIRECT
    assert by_target["Cube_C"].depth == 2
    assert by_target["Cube_C"].path == ("Process_A", "Process_B", "Cube_C")


# ---------------------------------------------------------------------------
# 16. TM1 场景：Rule → Cube（沿用 DependencyKind）
# ---------------------------------------------------------------------------
def test_rule_to_cube():
    deps = [
        _dep(DependencyKind.RULE_REFERENCES_CUBE, "Rule_A", "Cube_B"),
    ]
    impacts = analyze_impact(deps, "Rule_A")

    assert len(impacts) == 1
    assert impacts[0].target == "Cube_B"
    assert impacts[0].kind == ImpactKind.DIRECT
    assert impacts[0].depth == 1


# ---------------------------------------------------------------------------
# 17. unknown source（不发明影响）
# ---------------------------------------------------------------------------
def test_unknown_source():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    assert analyze_impact(deps, "Z") == []


# ---------------------------------------------------------------------------
# 18. duplicate dependencies（去重后结果稳定，不重复 target）
# ---------------------------------------------------------------------------
def test_duplicate_dependencies():
    deps = [
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),
        _dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B"),  # 重复
        _dep(DependencyKind.PROCESS_WRITES_CUBE, "B", "C"),
    ]
    impacts = analyze_impact(deps, "A")

    targets = [i.target for i in impacts]
    assert len(targets) == len(set(targets))
    assert set(targets) == {"B", "C"}


# ---------------------------------------------------------------------------
# 19. no Graph DB dependency
# ---------------------------------------------------------------------------
def test_impact_module_has_no_forbidden_dependency():
    import ast
    import tm1_insight.impact.engine as ie

    with open(ie.__file__, "r", encoding="utf-8") as f:
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


# ---------------------------------------------------------------------------
# 20. ImpactEngine class API + get_impact 便捷函数
# ---------------------------------------------------------------------------
def test_impact_engine_class_api():
    engine = ImpactEngine()
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    impacts = engine.analyze_impact(deps, "A")
    assert len(impacts) == 1
    assert impacts[0].source == "A"
    assert impacts[0].target == "B"
    assert impacts[0].kind == ImpactKind.DIRECT


def test_get_impact_alias():
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "A", "B")]
    assert [(i.target, i.kind) for i in get_impact(deps, "A")] == \
        [(i.target, i.kind) for i in analyze_impact(deps, "A")]
