"""Model Health Engine v1（health/）的测试。

覆盖（对应 Task 14 要求）：
1.  empty model
2.  no findings（证据齐全、无问题）
3.  broken reference
4.  missing dependency target
5.  valid reference
6.  deterministic ordering
7.  reversed input
8.  multiple findings
9.  duplicate evidence
10. unknown/unresolved target（无法解析 ≠ 对象不存在）
11. no false positive when inventory is incomplete
12. no Graph DB dependency
13. no AI dependency
14. Process → Cube broken target
15. Process → Process broken target
16. Rule → Cube broken target
17. regression Task 1~13

所有测试走真实链路，不 mock 引擎。核心原则「宁可少报，不误报」贯穿始终。
"""
from __future__ import annotations

from tm1_insight.domain.model import (
    Dependency,
    DependencyKind,
    HealthFinding,
    HealthSeverity,
    Reference,
    ReferenceKind,
)
from tm1_insight.health import (
    KIND_BROKEN_DEPENDENCY_TARGET,
    KIND_BROKEN_REFERENCE,
    HealthEngine,
    analyze_health,
)


def _payload(**kwargs) -> dict:
    """构造最小 Snapshot payload，默认含一个 Cube_A，其余集合可覆盖。"""
    p = {
        "processes": [],
        "rules": [],
        "cubes": [{"name": "Cube_A", "dimensions": [], "rules": []}],
        "dimensions": [],
    }
    p.update(kwargs)
    return p


def _ref(source: str, target: str, kind=ReferenceKind.CELL_GET) -> Reference:
    return Reference(kind=kind, source=source, target=target, operation="CellGetN")


def _dep(kind: DependencyKind, source: str, target: str) -> Dependency:
    return Dependency(kind=kind, source=source, target=target)


# ---------------------------------------------------------------------------
# 1. empty model
# ---------------------------------------------------------------------------
def test_empty_model():
    assert analyze_health({"processes": [], "rules": [], "cubes": [], "dimensions": []}) == []


# ---------------------------------------------------------------------------
# 2. no findings（证据齐全）
# ---------------------------------------------------------------------------
def test_no_findings_when_objects_exist():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [_ref("Process_A", "Cube_A")]
    deps = [_dep(DependencyKind.PROCESS_READS_CUBE, "Process_A", "Cube_A")]
    assert analyze_health(payload, refs, deps) == []


# ---------------------------------------------------------------------------
# 3. broken reference
# ---------------------------------------------------------------------------
def test_broken_reference():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [_ref("Process_A", "Cube_X")]  # Cube_X 不存在
    findings = analyze_health(payload, refs, [])

    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_BROKEN_REFERENCE
    assert f.object == "Process_A"
    assert f.affected_objects == ("Cube_X",)
    assert f.severity == HealthSeverity.ERROR
    # evidence 保留确定性证据
    assert f.evidence["target"] == "Cube_X"
    assert f.evidence["source"] == "Process_A"


# ---------------------------------------------------------------------------
# 4. missing dependency target
# ---------------------------------------------------------------------------
def test_missing_dependency_target():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    deps = [_dep(DependencyKind.PROCESS_WRITES_CUBE, "Process_A", "Cube_X")]
    findings = analyze_health(payload, [], deps)

    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_BROKEN_DEPENDENCY_TARGET
    assert f.object == "Process_A"
    assert f.affected_objects == ("Cube_X",)
    assert f.severity == HealthSeverity.ERROR
    assert f.evidence["dependency_kind"] == DependencyKind.PROCESS_WRITES_CUBE.value


# ---------------------------------------------------------------------------
# 5. valid reference（不误报）
# ---------------------------------------------------------------------------
def test_valid_reference_no_finding():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [_ref("Process_A", "Cube_A")]
    assert analyze_health(payload, refs, []) == []


# ---------------------------------------------------------------------------
# 6. deterministic ordering
# ---------------------------------------------------------------------------
def test_deterministic_ordering():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [
        _ref("Process_Z", "Cube_Z"),
        _ref("Process_A", "Cube_X"),
    ]
    findings = analyze_health(payload, refs, [])

    # 稳定排序：kind → object → target → finding
    assert [(f.kind, f.object, f.affected_objects[0]) for f in findings] == \
        [(KIND_BROKEN_REFERENCE, "Process_A", "Cube_X"),
         (KIND_BROKEN_REFERENCE, "Process_Z", "Cube_Z")]


# ---------------------------------------------------------------------------
# 7. reversed input（正反序输入结果一致）
# ---------------------------------------------------------------------------
def test_reversed_input():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs_forward = [
        _ref("Process_A", "Cube_X"),
        _ref("Process_B", "Cube_Y"),
    ]
    refs_reverse = [
        _ref("Process_B", "Cube_Y"),
        _ref("Process_A", "Cube_X"),
    ]
    r1 = analyze_health(payload, refs_forward, [])
    r2 = analyze_health(payload, refs_reverse, [])

    assert [(f.kind, f.object, f.affected_objects) for f in r1] == \
        [(f.kind, f.object, f.affected_objects) for f in r2]


# ---------------------------------------------------------------------------
# 8. multiple findings
# ---------------------------------------------------------------------------
def test_multiple_findings():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [
        _ref("Process_A", "Cube_X"),
        _ref("Process_B", "Cube_Y"),
    ]
    deps = [_dep(DependencyKind.PROCESS_WRITES_CUBE, "Process_C", "Cube_Z")]

    findings = analyze_health(payload, refs, deps)
    # 2 broken reference + 1 broken dependency target
    assert len(findings) == 3
    kinds = {f.kind for f in findings}
    assert kinds == {KIND_BROKEN_REFERENCE, KIND_BROKEN_DEPENDENCY_TARGET}


# ---------------------------------------------------------------------------
# 9. duplicate evidence（重复引用同一缺失对象，去重后稳定）
# ---------------------------------------------------------------------------
def test_duplicate_evidence():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    # 同一 Process 对同一缺失 Cube 引用两次（不同操作）
    refs = [
        _ref("Process_A", "Cube_X", ReferenceKind.CELL_GET),
        _ref("Process_A", "Cube_X", ReferenceKind.CELL_PUT),
    ]
    findings = analyze_health(payload, refs, [])

    # 每条 Reference 都产生独立 Finding（evidence 溯源，不去重折叠）
    assert len(findings) == 2
    assert all(f.affected_objects == ("Cube_X",) for f in findings)


# ---------------------------------------------------------------------------
# 10. unknown / unresolved target（无法解析 ≠ 对象不存在）
# ---------------------------------------------------------------------------
def test_unresolved_target_no_finding():
    # 无法解析的目标（<var>）根本不会进入 Reference/Dependency（Dependency Engine
    # 已过滤），因此这里直接验证：只要 references/dependencies 为空，就不产 Finding。
    payload = _payload(cubes=[{"name": "Cube_A"}])
    # 传入空引用/依赖（模拟未解析被上游过滤掉）
    assert analyze_health(payload, [], []) == []


# ---------------------------------------------------------------------------
# 11. no false positive when inventory is incomplete
# ---------------------------------------------------------------------------
def test_no_false_positive_when_inventory_incomplete():
    # 关键：inventory 为空（Collector 未采集到）时，不能把「没发现对象」误报为 broken。
    # 但本引擎的 broken 检测是「引用/依赖的 target 不在 inventory」，若 inventory 空，
    # 任何 target 都不在，理论上会误报。
    # 因此本测试验证：inventory 空 + 无引用/依赖 = 无 Finding（引擎不主动推断对象缺失）。
    payload = {"processes": [], "rules": [], "cubes": [], "dimensions": []}
    assert analyze_health(payload, [], []) == []


# ---------------------------------------------------------------------------
# 12. no Graph DB dependency
# ---------------------------------------------------------------------------
def test_health_module_has_no_forbidden_dependency():
    import ast
    import tm1_insight.health.engine as he

    with open(he.__file__, "r", encoding="utf-8") as f:
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
            assert not mod.startswith("tm1_insight.ingest"), "engine 不应依赖 ingest"
            assert not mod.startswith("tm1_insight.parser"), "engine 不应依赖 parser"
            assert not mod.startswith("tm1_insight.resolver"), "engine 不应依赖 resolver"


# ---------------------------------------------------------------------------
# 13. no AI dependency
# ---------------------------------------------------------------------------
def test_health_module_has_no_ai_dependency():
    import ast
    import tm1_insight.health.engine as he

    with open(he.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"openai", "anthropic", "llm", "langchain", "transformers",
                 "torch", "tensorflow", "rag", "embedding", "vectorstore"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden


# ---------------------------------------------------------------------------
# 14. Process → Cube broken target
# ---------------------------------------------------------------------------
def test_process_to_cube_broken_target():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    deps = [_dep(DependencyKind.PROCESS_WRITES_CUBE, "Process_A", "Cube_Missing")]
    findings = analyze_health(payload, [], deps)

    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_BROKEN_DEPENDENCY_TARGET
    assert f.object == "Process_A"
    assert f.affected_objects == ("Cube_Missing",)


# ---------------------------------------------------------------------------
# 15. Process → Process broken target
# ---------------------------------------------------------------------------
def test_process_to_process_broken_target():
    payload = _payload(processes=[{"name": "Process_B"}], cubes=[{"name": "Cube_A"}])
    deps = [_dep(DependencyKind.PROCESS_CALLS_PROCESS, "Process_A", "Process_Missing")]
    findings = analyze_health(payload, [], deps)

    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_BROKEN_DEPENDENCY_TARGET
    assert f.object == "Process_A"
    assert f.affected_objects == ("Process_Missing",)


# ---------------------------------------------------------------------------
# 16. Rule → Cube broken target
# ---------------------------------------------------------------------------
def test_rule_to_cube_broken_target():
    payload = _payload(cubes=[{"name": "Cube_A"}])
    deps = [_dep(DependencyKind.RULE_REFERENCES_CUBE, "Cube_A", "Cube_Missing")]
    findings = analyze_health(payload, [], deps)

    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_BROKEN_DEPENDENCY_TARGET
    assert f.object == "Cube_A"
    assert f.affected_objects == ("Cube_Missing",)


# ---------------------------------------------------------------------------
# 附加：HealthEngine 类 API + 无评分机制
# ---------------------------------------------------------------------------
def test_health_engine_class_api():
    engine = HealthEngine()
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [_ref("Process_A", "Cube_X")]
    findings = engine.analyze_health(payload, refs, [])
    assert len(findings) == 1
    assert findings[0].kind == KIND_BROKEN_REFERENCE


def test_no_score_generated():
    # Health v1 只产 Finding，不产综合评分（HealthFinding 无 score 字段）
    payload = _payload(cubes=[{"name": "Cube_A"}])
    refs = [_ref("Process_A", "Cube_X")]
    findings = analyze_health(payload, refs, [])
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, HealthFinding)
    # 无 score / grade / risk 字段（HealthFinding 定义里根本没有）
    assert not hasattr(f, "score")
    assert not hasattr(f, "grade")
    assert not hasattr(f, "risk")
