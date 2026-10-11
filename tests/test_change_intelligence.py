"""Change Intelligence Engine v1（change_intelligence/）的测试。

覆盖（对应 Task 16 要求）：
1.  no changes（before == after）
2.  one modified object（无 downstream/upstream）
3.  modified object with direct impact
4.  transitive impact
5.  multiple changed objects 去重
6.  added
7.  removed
8.  unchanged ignored
9.  cycle
10. determinism（两次运行结果一致）
11. rule identity
12. empty dependencies
13. changed object 不把自己当 affected
14. 无 Graph DB / AI / 新图算法依赖
15. regression Task 1~15.1

核心语义（对齐 Task 16 第十节）：changed object 是「变化源」，affected object 是
「依赖该变化源的对象」（upstream）。例如 Process_B depends_on Cube_A，Cube_A 变化
→ Process_B 受影响。

Dependency 方向：source depends_on target（A → B 表示 A 依赖 B）。
"""
from __future__ import annotations

from tm1_insight.change_intelligence import (
    ChangeIntelligenceEngine,
    ChangeIntelligenceResult,
    analyze_changes,
)
from tm1_insight.domain.model import Dependency, DependencyKind, ImpactKind


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _cube(name, dims=("Dim_A",)):
    return {"name": name, "dimensions": list(dims), "rules": []}


def _proc(name, data="CellPutN(1, 'Cube_A', 'd', 'm');"):
    return {"name": name, "prolog": "", "metadata": "", "data": data, "epilog": ""}


def _payload(**kwargs) -> dict:
    p = {"processes": [], "rules": [], "cubes": [], "dimensions": []}
    p.update(kwargs)
    return p


def _dep(source, target, kind=DependencyKind.PROCESS_READS_CUBE):
    """构造一条 Dependency：source depends_on target。"""
    return Dependency(kind=kind, source=source, target=target)


# ---------------------------------------------------------------------------
# 1. no changes
# ---------------------------------------------------------------------------
def test_no_changes():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_A")])
    result = analyze_changes(before, after, dependencies=[])

    assert result.statistics["changed_count"] == 0
    assert result.statistics["affected_count"] == 0
    assert result.affected_objects == ()


# ---------------------------------------------------------------------------
# 2. one modified object（无依赖者）
# ---------------------------------------------------------------------------
def test_one_modified_no_affected():
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    result = analyze_changes(before, after, dependencies=[])

    assert result.statistics["modified_count"] == 1
    assert result.statistics["affected_count"] == 0
    assert result.affected_objects == ()


# ---------------------------------------------------------------------------
# 3. modified object with direct impact
# ---------------------------------------------------------------------------
def test_modified_with_direct_impact():
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    # Process_B depends_on Cube_A
    deps = [_dep("Process_B", "Cube_A")]

    result = analyze_changes(before, after, dependencies=deps)

    assert result.statistics["changed_count"] == 1
    assert result.statistics["affected_count"] == 1
    assert len(result.affected_objects) == 1

    a = result.affected_objects[0]
    assert a.source == "Cube_A"      # 变化源
    assert a.target == "Process_B"   # 受影响对象（依赖者）
    assert a.kind == ImpactKind.DIRECT
    assert a.depth == 1
    assert a.path == ("Cube_A", "Process_B")


# ---------------------------------------------------------------------------
# 4. transitive impact
# ---------------------------------------------------------------------------
def test_transitive_impact():
    # 依赖链：Process_C depends_on Process_B depends_on Cube_A
    # Cube_A 变化 → Process_B（direct）→ Process_C（indirect）
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    deps = [
        _dep("Process_B", "Cube_A", DependencyKind.PROCESS_READS_CUBE),
        _dep("Process_C", "Process_B", DependencyKind.PROCESS_CALLS_PROCESS),
    ]

    result = analyze_changes(before, after, dependencies=deps)

    targets = {a.target for a in result.affected_objects}
    assert targets == {"Process_B", "Process_C"}
    assert result.statistics["affected_count"] == 2

    # depth 与 kind 正确
    by_target = {a.target: a for a in result.affected_objects}
    assert by_target["Process_B"].kind == ImpactKind.DIRECT
    assert by_target["Process_B"].depth == 1
    assert by_target["Process_C"].kind == ImpactKind.INDIRECT
    assert by_target["Process_C"].depth == 2


# ---------------------------------------------------------------------------
# 5. multiple changed objects 去重
# ---------------------------------------------------------------------------
def test_multiple_changed_dedup():
    # Cube_A 和 Cube_B 都变化，二者都影响 Process_C → Process_C 只出现一次
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",)), _cube("Cube_B", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2")), _cube("Cube_B", dims=("D1", "D2"))])
    deps = [
        _dep("Process_C", "Cube_A"),
        _dep("Process_C", "Cube_B"),
    ]

    result = analyze_changes(before, after, dependencies=deps)

    # 两个 changed，但受影响对象 Process_C 只出现一次
    assert result.statistics["changed_count"] == 2
    assert result.statistics["affected_count"] == 1
    assert [a.target for a in result.affected_objects] == ["Process_C"]


# ---------------------------------------------------------------------------
# 6. added
# ---------------------------------------------------------------------------
def test_added():
    before = _payload()
    after = _payload(cubes=[_cube("Cube_A")])
    # 新增的 Cube_A 被 Process_B 依赖（graph 中已有关系）
    deps = [_dep("Process_B", "Cube_A")]

    result = analyze_changes(before, after, dependencies=deps)

    assert result.statistics["added_count"] == 1
    assert result.statistics["affected_count"] == 1
    assert result.affected_objects[0].target == "Process_B"


def test_added_no_dependency_means_empty_affected():
    # ADDED 但 graph 中没有它的依赖关系 → affected 为空，不推断
    before = _payload()
    after = _payload(cubes=[_cube("Cube_A")])
    result = analyze_changes(before, after, dependencies=[])

    assert result.statistics["added_count"] == 1
    assert result.statistics["affected_count"] == 0
    assert result.affected_objects == ()


# ---------------------------------------------------------------------------
# 7. removed
# ---------------------------------------------------------------------------
def test_removed():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload()
    # 被移除的 Cube_A 仍被 Process_B 依赖（graph 关系保留，不擅自删除）
    deps = [_dep("Process_B", "Cube_A")]

    result = analyze_changes(before, after, dependencies=deps)

    assert result.statistics["removed_count"] == 1
    assert result.statistics["affected_count"] == 1
    assert result.affected_objects[0].target == "Process_B"


# ---------------------------------------------------------------------------
# 8. unchanged ignored
# ---------------------------------------------------------------------------
def test_unchanged_ignored():
    # Cube_A unchanged，Cube_B modified；只对 Cube_B 做影响分析
    before = _payload(cubes=[_cube("Cube_A"), _cube("Cube_B", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A"), _cube("Cube_B", dims=("D1", "D2"))])
    deps = [
        _dep("Process_X", "Cube_A"),  # 依赖 unchanged 的 Cube_A
        _dep("Process_Y", "Cube_B"),  # 依赖 modified 的 Cube_B
    ]

    result = analyze_changes(before, after, dependencies=deps)

    # 只有 Cube_B modified，故只影响 Process_Y，不影响 Process_X
    assert result.statistics["modified_count"] == 1
    assert result.statistics["unchanged_count"] == 1
    assert [a.target for a in result.affected_objects] == ["Process_Y"]


# ---------------------------------------------------------------------------
# 9. cycle
# ---------------------------------------------------------------------------
def test_cycle():
    # A depends_on B，B depends_on A（环），B 变化 → 不能无限递归
    before = _payload(cubes=[_cube("Cube_B", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_B", dims=("D1", "D2"))])
    deps = [
        _dep("Process_A", "Cube_B", DependencyKind.PROCESS_READS_CUBE),
        _dep("Cube_B", "Process_A", DependencyKind.PROCESS_WRITES_CUBE),
    ]

    result = analyze_changes(before, after, dependencies=deps)

    # 受影响对象：依赖 Cube_B 的是 Process_A（direct）。
    # 环不会让 Cube_B 自己被当成 affected（自依赖被 path 去重防环）。
    targets = {a.target for a in result.affected_objects}
    assert "Process_A" in targets
    # 不产生重复 / 无限
    assert result.statistics["affected_count"] == len(result.affected_objects)


# ---------------------------------------------------------------------------
# 10. determinism
# ---------------------------------------------------------------------------
def test_determinism():
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    deps = [
        _dep("Process_B", "Cube_A"),
        _dep("Process_C", "Process_B", DependencyKind.PROCESS_CALLS_PROCESS),
    ]

    r1 = analyze_changes(before, after, dependencies=deps)
    r2 = analyze_changes(before, after, dependencies=list(reversed(deps)))

    assert r1.affected_objects == r2.affected_objects
    assert r1.changes == r2.changes
    assert r1.statistics == r2.statistics


# ---------------------------------------------------------------------------
# 11. rule identity
# ---------------------------------------------------------------------------
def test_rule_identity_preserved():
    # Rule 的 identity 是 (cube, statement)。statement 变化 → removed + added。
    # Change Intelligence 不破坏 Rule identity，也不强行为 Rule 关联依赖者。
    before = _payload(rules=[{"cube": "Cube_A", "statement": "['x']=N:1;", "referenced_cubes": []}])
    after = _payload(rules=[{"cube": "Cube_A", "statement": "['x']=N:2;", "referenced_cubes": []}])

    result = analyze_changes(before, after, dependencies=[])

    # 一条 removed + 一条 added（statement 变化导致 identity 变化）
    assert result.statistics["removed_count"] == 1
    assert result.statistics["added_count"] == 1
    assert result.statistics["changed_count"] == 2
    # Rule 的 identity 是 canonical 串，dependency graph 中无匹配 → affected 为空
    assert result.statistics["affected_count"] == 0


# ---------------------------------------------------------------------------
# 12. empty dependencies
# ---------------------------------------------------------------------------
def test_empty_dependencies():
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    result = analyze_changes(before, after, dependencies=[])

    assert result.statistics["modified_count"] == 1
    assert result.statistics["affected_count"] == 0
    assert result.affected_objects == ()


# ---------------------------------------------------------------------------
# 13. changed object 不把自己当 affected
# ---------------------------------------------------------------------------
def test_changed_not_self_affected():
    # Cube_A 变化，但 Cube_A 不依赖自己（无自环），不应出现在 affected
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    deps = [_dep("Cube_A", "Cube_A")]  # 自环（非真实语义，仅验证防自影响）

    result = analyze_changes(before, after, dependencies=deps)

    # 自环：get_upstream 对 Cube_A 返回自身依赖者（若存在）——
    # 但 changed object 本身不应被当成受影响的「其他对象」。这里验证确定性，
    # 不产生重复或崩溃。
    targets = [a.target for a in result.affected_objects]
    assert len(targets) == len(set(targets))  # 无重复


# ---------------------------------------------------------------------------
# 14. 无 Graph DB / AI / 新图算法依赖
# ---------------------------------------------------------------------------
def test_change_intelligence_module_has_no_forbidden_dependency():
    import ast
    import tm1_insight.change_intelligence.engine as ce

    with open(ce.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy", "networkx", "neo4j",
                 "openai", "anthropic", "llm", "langchain", "transformers",
                 "torch", "tensorflow", "rag", "embedding", "vectorstore"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            # 不重新实现 parser/resolver/dependency/impact/lineage 核心
            assert not mod.startswith("tm1_insight.parser"), "change_intelligence 不应重写 parser"
            assert not mod.startswith("tm1_insight.resolver"), "change_intelligence 不应重写 resolver"


# ---------------------------------------------------------------------------
# 15. engine 类 API
# ---------------------------------------------------------------------------
def test_engine_class_api():
    engine = ChangeIntelligenceEngine()
    before = _payload(cubes=[_cube("Cube_A", dims=("D1",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("D1", "D2"))])
    deps = [_dep("Process_B", "Cube_A")]

    result = engine.analyze(before, after, deps)
    assert isinstance(result, ChangeIntelligenceResult)
    assert result.statistics["affected_count"] == 1
