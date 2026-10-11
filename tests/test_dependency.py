"""Dependency Engine（dependency/）的回归测试。

覆盖（对应 Task 6 要求）：
1.  Process → Cube（CellPut/CellGet 读写）
2.  Process → Process（ExecuteProcess）
3.  Rule → Cube（跨 cube 引用）
4.  Process → Dimension（本阶段**不支持**，锁定为不产出）
5.  未知目标（``<pCube>``）不产出错误 Dependency
6.  重复引用去重，references 全保留
7.  自依赖不误判（Rule(Cube_A) 不依赖 Cube_A）
8.  Determinism（同输入两次结果一致）
9.  Evidence 溯源（Dependency → Reference）
10. ExecuteProcess 不错误传播参数成 Process → Cube

测试数据均为最小匿名片段，不触碰生产数据 / 数据库 / 服务器。
"""
from __future__ import annotations

from tm1_suite.dependency import (
    DependencyEngine,
    build_dependencies,
    build_process_dependencies,
    build_rule_dependencies,
)
from tm1_suite.domain.model import (
    DependencyKind,
    Reference,
    ReferenceKind,
    Rule,
)
from tm1_suite.ingest import hard_extract as h


def _parsed(ti: dict) -> dict:
    return h.process_ti(ti)


def _ti(prolog="", metadata="", data="", epilog="", name="P", parameters=None):
    return {
        "name": name,
        "prolog": prolog,
        "metadata": metadata,
        "data": data,
        "epilog": epilog,
        "parameters": parameters or [],
    }


# ---------------------------------------------------------------------------
# 1. Process → Cube（读写）
# ---------------------------------------------------------------------------
def test_process_reads_and_writes_cube():
    ti = _ti(
        name="P_Load",
        data=(
            "v = CellGetN('Cube_Src', '2024', 'Amount');"
            "CellPutN(v, 'Cube_Tgt', '2024', 'Amount');"
        ),
    )
    deps = build_process_dependencies("P_Load", _parsed(ti))

    kinds = {(d.kind, d.source, d.target) for d in deps}
    assert (DependencyKind.PROCESS_READS_CUBE, "P_Load", "Cube_Src") in kinds
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P_Load", "Cube_Tgt") in kinds


def test_process_writes_cube_cellput():
    ti = _ti(name="P", data="CellPutN(100, 'Cube_A', '2024', 'Measure');")
    deps = build_process_dependencies("P", _parsed(ti))
    assert len(deps) == 1
    assert deps[0].kind == DependencyKind.PROCESS_WRITES_CUBE
    assert deps[0].source == "P"
    assert deps[0].target == "Cube_A"


# ---------------------------------------------------------------------------
# 2. Process → Process（ExecuteProcess）
# ---------------------------------------------------------------------------
def test_process_calls_process():
    ti = _ti(name="P_Master", data="ExecuteProcess('P_Child', 'pYear', '2024');")
    deps = build_process_dependencies("P_Master", _parsed(ti))
    assert len(deps) == 1
    assert deps[0].kind == DependencyKind.PROCESS_CALLS_PROCESS
    assert deps[0].source == "P_Master"
    assert deps[0].target == "P_Child"


def test_framework_call_is_not_process_dependency():
    ti = _ti(
        name="P",
        data="ExecuteProcess('}bedrock.cube.data.clear', 'pCube', 'Cube_A');",
    )
    deps = build_process_dependencies("P", _parsed(ti))
    # 框架调用不应产生 Process → Process 依赖
    assert not any(d.kind == DependencyKind.PROCESS_CALLS_PROCESS for d in deps)


# ---------------------------------------------------------------------------
# 3. Rule → Cube（跨 cube 引用）
# ---------------------------------------------------------------------------
def test_rule_references_cube():
    rule = Rule(cube="Cube_A", statement="['X']=N:...;", referenced_cubes=("Cube_B",))
    deps = build_rule_dependencies(rule)
    assert len(deps) == 1
    assert deps[0].kind == DependencyKind.RULE_REFERENCES_CUBE
    assert deps[0].source == "Cube_A"
    assert deps[0].target == "Cube_B"


# ---------------------------------------------------------------------------
# 4. Process → Dimension（本阶段不支持）
# ---------------------------------------------------------------------------
def test_process_to_dimension_not_yet_supported():
    # 当前 Parser 不提取 DimensionElementInsert 等维度操作，
    # 因此不应产出 Process → Dimension 依赖。
    ti = _ti(name="P", data="DimensionElementInsert('Dim_X', '', 'NewElem', 'n');")
    deps = build_process_dependencies("P", _parsed(ti))
    # 既无 Process → Dimension 依赖，也无其它凭空依赖
    assert deps == []


# ---------------------------------------------------------------------------
# 5. 未知目标不产出错误 Dependency
# ---------------------------------------------------------------------------
def test_unresolved_target_no_dependency():
    ti = _ti(name="P", data="CellPutN(100, pCube, '2024', 'Measure');")
    deps = build_process_dependencies("P", _parsed(ti))
    # pCube 未解析 → target_cube 为 <pCube>，不得产出 Dependency
    assert deps == []


def test_unresolved_callee_no_process_dependency():
    ti = _ti(name="P", data="ExecuteProcess(pProc, 'pYear', '2024');")
    deps = build_process_dependencies("P", _parsed(ti))
    assert not any(d.kind == DependencyKind.PROCESS_CALLS_PROCESS for d in deps)


# ---------------------------------------------------------------------------
# 6. 重复引用去重，references 全保留
# ---------------------------------------------------------------------------
def test_dedup_keeps_all_references():
    ti = _ti(
        name="P",
        data=(
            "CellPutN(1, 'Cube_A', 'd', 'm1');"
            "CellPutN(2, 'Cube_A', 'd', 'm2');"
            "CellGetN('Cube_A', 'd', 'm0');"
        ),
    )
    deps = build_process_dependencies("P", _parsed(ti))

    writes = [d for d in deps if d.kind == DependencyKind.PROCESS_WRITES_CUBE
              and d.target == "Cube_A"]
    reads = [d for d in deps if d.kind == DependencyKind.PROCESS_READS_CUBE
             and d.target == "Cube_A"]

    # 写引用去重为一条 Dependency，但保留两条 Reference
    assert len(writes) == 1
    assert len(writes[0].references) == 2
    # 读引用一条
    assert len(reads) == 1
    assert len(reads[0].references) == 1


# ---------------------------------------------------------------------------
# 7. 自依赖不误判
# ---------------------------------------------------------------------------
def test_rule_self_reference_not_dependency():
    rule = Rule(cube="Cube_A", statement="...;", referenced_cubes=("Cube_A",))
    deps = build_rule_dependencies(rule)
    assert deps == []


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------
def test_determinism():
    ti = _ti(
        name="P_Load",
        prolog="vCube = 'Cube_A';",
        data=(
            "CellPutN(1, vCube, 'd', 'm1');"
            "CellGetN('Cube_Src', 'd', 'm0');"
            "ExecuteProcess('P_Child', 'pYear', '2024');"
            "CellPutN(2, vCube, 'd', 'm2');"
        ),
    )
    r1 = build_process_dependencies("P_Load", _parsed(ti))
    r2 = build_process_dependencies("P_Load", _parsed(ti))
    assert r1 == r2


def test_stable_sorting():
    ti = _ti(
        name="P",
        data=(
            "CellPutN(1, 'Cube_Z', 'd', 'm');"
            "CellPutN(2, 'Cube_A', 'd', 'm');"
            "ExecuteProcess('P_B', 'pYear', '2024');"
            "ExecuteProcess('P_A', 'pYear', '2024');"
        ),
    )
    r1 = build_process_dependencies("P", _parsed(ti))
    r2 = build_process_dependencies("P", _parsed(ti))
    # 排序确定性：两次运行顺序一致
    assert [d.target for d in r1] == [d.target for d in r2]
    # 同一 kind 内按 target 字典序
    calls = [d for d in r1 if d.kind == DependencyKind.PROCESS_CALLS_PROCESS]
    assert [d.target for d in calls] == ["P_A", "P_B"]


# ---------------------------------------------------------------------------
# 9. Evidence 溯源（Dependency → Reference）
# ---------------------------------------------------------------------------
def test_dependency_traces_to_reference():
    ti = _ti(name="P", data="CellPutN(100, 'Cube_A', '2024', 'Measure');")
    deps = build_process_dependencies("P", _parsed(ti))
    dep = deps[0]

    assert dep.references
    ref = dep.references[0]
    assert isinstance(ref, Reference)
    assert ref.kind == ReferenceKind.CELL_PUT
    assert ref.operation == "CellPutN"
    assert ref.source == "P"
    assert ref.target == "Cube_A"
    # evidence 携带操作细节（未来 UI 展示 "Why?"）
    assert ref.evidence["target_cube_expr"] == "'Cube_A'"


# ---------------------------------------------------------------------------
# 10. ExecuteProcess 不错误传播参数
# ---------------------------------------------------------------------------
def test_execute_process_no_argument_propagation():
    # Process_A 调 Process_B，传了 pCube=Cube_A。
    # 本阶段只应产出 Process_A → Process_B，
    # 不应错误地传播成 Process_A → Cube_A。
    ti = _ti(
        name="Process_A",
        data="ExecuteProcess('Process_B', 'pCube', 'Cube_A');",
    )
    deps = build_process_dependencies("Process_A", _parsed(ti))

    assert len(deps) == 1
    assert deps[0].kind == DependencyKind.PROCESS_CALLS_PROCESS
    assert deps[0].target == "Process_B"
    assert not any(d.target == "Cube_A" for d in deps)


# ---------------------------------------------------------------------------
# 附加：build_dependencies 一站式入口 + 无外部依赖
# ---------------------------------------------------------------------------
def test_build_dependencies_combined():
    ti = _ti(name="P", data="CellPutN(1, 'Cube_A', 'd', 'm');")
    rule = Rule(cube="Cube_X", referenced_cubes=("Cube_A", "Cube_B"))
    deps = build_dependencies(processes=[_parsed(ti)], rules=[rule])

    kinds = {(d.kind, d.source, d.target) for d in deps}
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P", "Cube_A") in kinds
    assert (DependencyKind.RULE_REFERENCES_CUBE, "Cube_X", "Cube_A") in kinds
    assert (DependencyKind.RULE_REFERENCES_CUBE, "Cube_X", "Cube_B") in kinds


def test_dependency_module_has_no_duckdb_dependency():
    import ast
    import tm1_suite.dependency.engine as de

    with open(de.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy", "networkx", "neo4j"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            assert not mod.startswith("tm1_suite.snapshot"), "engine 不应依赖 snapshot"
            assert not mod.startswith("tm1_suite.api"), "engine 不应依赖 api"


# ---------------------------------------------------------------------------
# Task 10 新增：Bedrock copy 经真实链路产生正确的 read/write dependency
# ---------------------------------------------------------------------------
def test_bedrock_copy_read_and_write_dependency():
    # 走真实链路：TI Code → Parser → Dependency Engine
    ti = _ti(
        name="P_Copy",
        data=(
            "ExecuteProcess('}bedrock.cube.data.copy', "
            "'pLogOutput', 0, 'pSrcCube', 'Cube_Src', 'pTgtCube', 'Cube_Tgt', "
            "'pMappingToNewDims', '', 'pSuppressConsolidation', 0);"
        ),
    )
    deps = build_process_dependencies("P_Copy", _parsed(ti))

    kinds = {(d.kind, d.source, d.target) for d in deps}
    assert (DependencyKind.PROCESS_READS_CUBE, "P_Copy", "Cube_Src") in kinds
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P_Copy", "Cube_Tgt") in kinds
    # 框架调用不产生 Process → Process 依赖
    assert not any(d.kind == DependencyKind.PROCESS_CALLS_PROCESS for d in deps)
