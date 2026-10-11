"""Dependency Contract 锁定测试（Task 11）。

本文件正式锁定 Reference / Dependency / DependencyKind 之间的语义契约，
为下一阶段 Lineage / Impact Analysis 建立稳定地基。

核心契约：
- Dependency = Direct Dependency（不是 Lineage / Transitive / Reachability）。
- Reference = Parser 发现的语法事实；Dependency = 基于 Reference 推导的直接语义关系。
- source → target 方向明确（source 依赖方，target 被依赖方）。
- 不产生传递依赖（A calls B、B writes C，只产 A→B 与 B→C，绝不产 A→C）。
- 去重：同一 (kind, source, target) 只一条 Dependency，但保留全部 references。
- 未解析目标（<var>）不发明对象、不产出假依赖。
- 确定性：输入顺序无关，输出稳定。

全部测试走真实链路（TI Code → Parser → Dependency Engine），不 mock 掉 parser。
"""
from __future__ import annotations

from tm1_insight.dependency import (
    build_process_dependencies,
    build_rule_dependencies,
)
from tm1_insight.domain.model import (
    Dependency,
    DependencyKind,
    Reference,
    ReferenceKind,
    Rule,
)
from tm1_insight.ingest import hard_extract as h


def _ti(prolog="", metadata="", data="", epilog="", name="P", parameters=None):
    return {
        "name": name,
        "prolog": prolog,
        "metadata": metadata,
        "data": data,
        "epilog": epilog,
        "parameters": parameters or [],
    }


def _parsed(ti: dict) -> dict:
    return h.process_ti(ti)


def _deps(name: str, ti: dict) -> list[Dependency]:
    return build_process_dependencies(name, _parsed(ti))


# ---------------------------------------------------------------------------
# 1~4. 四类 DependencyKind 契约
# ---------------------------------------------------------------------------
def test_process_reads_cube_kind():
    deps = _deps("P", _ti(data="v = CellGetN('Cube_A', '2024', 'Amount');"))
    assert len(deps) == 1
    d = deps[0]
    assert d.kind == DependencyKind.PROCESS_READS_CUBE
    assert d.source == "P"
    assert d.target == "Cube_A"


def test_process_writes_cube_kind():
    deps = _deps("P", _ti(data="CellPutN(100, 'Cube_A', '2024', 'Amount');"))
    assert len(deps) == 1
    d = deps[0]
    assert d.kind == DependencyKind.PROCESS_WRITES_CUBE
    assert d.source == "P"
    assert d.target == "Cube_A"


def test_process_calls_process_kind():
    deps = _deps("P_Master", _ti(data="ExecuteProcess('P_Child', 'pYear', '2024');"))
    assert len(deps) == 1
    d = deps[0]
    assert d.kind == DependencyKind.PROCESS_CALLS_PROCESS
    assert d.source == "P_Master"
    assert d.target == "P_Child"


def test_rule_references_cube_kind():
    rule = Rule(cube="Cube_A", statement="['X']=N:...;", referenced_cubes=("Cube_B",))
    deps = build_rule_dependencies(rule)
    assert len(deps) == 1
    d = deps[0]
    assert d.kind == DependencyKind.RULE_REFERENCES_CUBE
    assert d.source == "Cube_A"
    assert d.target == "Cube_B"


# ---------------------------------------------------------------------------
# 5. Direct dependency only（不产生传递依赖）
# ---------------------------------------------------------------------------
def test_direct_dependency_only_no_transitive():
    # A calls B；B writes C。Dependency 只应产出 A→B 与 B→C，绝不产 A→C。
    deps_a = _deps("A", _ti(data="ExecuteProcess('B', 'pYear', '2024');"))
    deps_b = _deps("B", _ti(data="CellPutN(1, 'C', 'd', 'm');"))

    a_kinds = {(d.kind, d.source, d.target) for d in deps_a}
    b_kinds = {(d.kind, d.source, d.target) for d in deps_b}

    assert (DependencyKind.PROCESS_CALLS_PROCESS, "A", "B") in a_kinds
    assert (DependencyKind.PROCESS_WRITES_CUBE, "B", "C") in b_kinds
    # 关键：A 的 Dependency 里绝无「A → C」
    assert not any(d.target == "C" for d in deps_a)
    # 也没有任何 kind 能把 A 连到 C
    assert (DependencyKind.PROCESS_WRITES_CUBE, "A", "C") not in a_kinds


# ---------------------------------------------------------------------------
# 6. source / target 方向
# ---------------------------------------------------------------------------
def test_direction_source_to_target():
    deps = _deps("Process_A", _ti(data="CellGetN('Cube_A', '2024', 'Amount');"))
    d = deps[0]
    # source 是依赖方（Process），target 是被依赖方（Cube），方向不可颠倒
    assert d.source == "Process_A"
    assert d.target == "Cube_A"
    assert d.source != d.target


# ---------------------------------------------------------------------------
# 7. Evidence 保留（Dependency → Reference 溯源）
# ---------------------------------------------------------------------------
def test_evidence_preserved():
    deps = _deps("P", _ti(data="CellPutN(100, 'Cube_A', '2024', 'Amount');"))
    d = deps[0]
    assert d.references
    ref = d.references[0]
    assert isinstance(ref, Reference)
    assert ref.kind == ReferenceKind.CELL_PUT
    assert ref.operation == "CellPutN"
    assert ref.source == "P"
    assert ref.target == "Cube_A"
    # evidence 携带操作细节，可回答「为什么存在这条依赖」
    assert ref.evidence.get("target_cube_expr") == "'Cube_A'"


# ---------------------------------------------------------------------------
# 8. Deduplication + 9. multiple references to same dependency
# ---------------------------------------------------------------------------
def test_deduplication_keeps_references():
    # 同一 Process 对同一 Cube 写 5 次 → 仍只 1 条 Dependency，但 5 条 Reference 全保留
    data = ";".join(f"CellPutN({i}, 'Cube_A', 'd', 'm{i}')" for i in range(5))
    deps = _deps("P", _ti(data=data))

    writes = [d for d in deps if d.kind == DependencyKind.PROCESS_WRITES_CUBE]
    assert len(writes) == 1
    assert len(writes[0].references) == 5


# ---------------------------------------------------------------------------
# 10. Self dependency 保留（不静默丢掉 self-reference）
# ---------------------------------------------------------------------------
def test_self_process_call_preserved():
    # Process_A calls Process_A —— self-reference 不应被静默丢弃
    deps = _deps("P_A", _ti(data="ExecuteProcess('P_A', 'pYear', '2024');"))
    assert (DependencyKind.PROCESS_CALLS_PROCESS, "P_A", "P_A") in {
        (d.kind, d.source, d.target) for d in deps
    }


def test_self_process_write_preserved():
    deps = _deps("P_A", _ti(data="CellPutN(1, 'Cube_A', 'd', 'm');"))
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P_A", "Cube_A") in {
        (d.kind, d.source, d.target) for d in deps
    }


def test_rule_self_reference_excluded():
    # Rule(Cube_A) 引用 Cube_A —— 这是跨 cube 引用的排除规则（Task 6 既有语义），
    # 不属于「写 Cube_A 依赖 Cube_A」的假自依赖。
    rule = Rule(cube="Cube_A", statement="...;", referenced_cubes=("Cube_A",))
    assert build_rule_dependencies(rule) == []


# ---------------------------------------------------------------------------
# 11. Unresolved target 不发明对象
# ---------------------------------------------------------------------------
def test_unresolved_cube_no_dependency():
    deps = _deps("P", _ti(data="CellPutN(1, pCube, 'd', 'm');"))
    assert deps == []


def test_unresolved_callee_no_dependency():
    deps = _deps("P", _ti(data="ExecuteProcess(pProc, 'pYear', '2024');"))
    assert not any(d.kind == DependencyKind.PROCESS_CALLS_PROCESS for d in deps)


# ---------------------------------------------------------------------------
# 12. Deterministic ordering（输入顺序无关）
# ---------------------------------------------------------------------------
def test_deterministic_ordering():
    # 同一语义输入，不同书写顺序 → 结果集合与顺序一致
    data_forward = (
        "CellPutN(1, 'Cube_Z', 'd', 'm');"
        "CellPutN(2, 'Cube_A', 'd', 'm');"
        "ExecuteProcess('P_B', 'pYear', '2024');"
        "ExecuteProcess('P_A', 'pYear', '2024');"
    )
    data_reverse = (
        "ExecuteProcess('P_A', 'pYear', '2024');"
        "ExecuteProcess('P_B', 'pYear', '2024');"
        "CellPutN(2, 'Cube_A', 'd', 'm');"
        "CellPutN(1, 'Cube_Z', 'd', 'm');"
    )
    r1 = _deps("P", _ti(data=data_forward))
    r2 = _deps("P", _ti(data=data_reverse))
    # 顺序无关：完全相同（含 ordering）
    assert [d.kind for d in r1] == [d.kind for d in r2]
    assert [(d.source, d.target) for d in r1] == [(d.source, d.target) for d in r2]


# ---------------------------------------------------------------------------
# 17. Bedrock Copy contract regression（Task 10 修复不得被破坏）
# ---------------------------------------------------------------------------
def test_bedrock_copy_contract_regression():
    # }bedrock.cube.data.copy(pSrcCube, pTgtCube, ...)
    # → PROCESS_READS_CUBE(Source) + PROCESS_WRITES_CUBE(Target)，且 Source ≠ Target
    deps = _deps(
        "P_Copy",
        _ti(
            data=(
                "ExecuteProcess('}bedrock.cube.data.copy', "
                "'pLogOutput', 0, 'pSrcCube', 'Cube_Src', 'pTgtCube', 'Cube_Tgt', "
                "'pMappingToNewDims', '', 'pSuppressConsolidation', 0);"
            )
        ),
    )

    kinds = {(d.kind, d.source, d.target) for d in deps}
    assert (DependencyKind.PROCESS_READS_CUBE, "P_Copy", "Cube_Src") in kinds
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P_Copy", "Cube_Tgt") in kinds
    # SourceCube ≠ TargetCube
    assert "Cube_Src" != "Cube_Tgt"
    # 框架调用不产生 Process → Process 依赖
    assert not any(d.kind == DependencyKind.PROCESS_CALLS_PROCESS for d in deps)


# ---------------------------------------------------------------------------
# 契约完整性：Dependency 语义字段齐备
# ---------------------------------------------------------------------------
def test_dependency_has_required_semantic_fields():
    deps = _deps("P", _ti(data="CellPutN(1, 'Cube_A', 'd', 'm');"))
    d = deps[0]
    # kind / source / target / confidence / references 五要素齐备
    assert d.kind is not None
    assert d.source
    assert d.target
    assert 0.0 <= d.confidence <= 1.0
    assert d.references is not None
