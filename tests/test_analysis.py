"""Analysis Assembly（analysis/）的回归测试。

覆盖（对应 Task 7 要求）：
1.  最小 Snapshot（1 Process + 1 Cube）产生正确 Dependency
2.  Process → Process（ExecuteProcess）
3.  Rule → Cube（跨 cube 引用）
4.  多个 Process 全部被分析
5.  空 Snapshot 得到合法 AnalysisResult（不异常）
6.  未知对象（applications/worksheets）正常跳过
7.  Determinism（同 Snapshot 两次结果一致）
8.  Snapshot immutability（分析前后 payload 不变）
9.  Statistics 正确
10. Evidence 保留（references 不丢失）
11. 回归：Task 1~6 全通过（由全量 pytest 保证）

测试只使用最小 fixture，不连接 TM1 Server、不扫描真实 DuckDB。
"""
from __future__ import annotations

from tm1_suite.analysis import analyze_snapshot
from tm1_suite.domain.model import DependencyKind, Process, Rule


# ---------------------------------------------------------------------------
# fixture：最小 Snapshot payload
# ---------------------------------------------------------------------------
def _process(name, code, parameters=None):
    """构造一个 Domain Process 条目（也可用 dict，测试里两者都覆盖）。"""
    return Process(name=name, code=code, parameters=parameters or ())


def _rule(cube, referenced_cubes, statement=""):
    return Rule(cube=cube, statement=statement, referenced_cubes=referenced_cubes)


# ---------------------------------------------------------------------------
# 1. 最小 Snapshot：1 Process 写 1 Cube
# ---------------------------------------------------------------------------
def test_minimal_snapshot_process_writes_cube():
    payload = {
        "processes": [
            _process("P_Load", "CellPutN(100, 'Cube_A', '2024', 'Measure');"),
        ],
    }
    result = analyze_snapshot(payload, snapshot_id="snap-001")

    assert result.snapshot_id == "snap-001"
    kinds = {(d.kind, d.source, d.target) for d in result.dependencies}
    assert (DependencyKind.PROCESS_WRITES_CUBE, "P_Load", "Cube_A") in kinds


# ---------------------------------------------------------------------------
# 2. Process → Process
# ---------------------------------------------------------------------------
def test_process_calls_process():
    payload = {
        "processes": [
            _process("Process_A", "ExecuteProcess('Process_B', 'pYear', '2024');"),
        ],
    }
    result = analyze_snapshot(payload, "snap")

    assert len(result.dependencies) == 1
    d = result.dependencies[0]
    assert d.kind == DependencyKind.PROCESS_CALLS_PROCESS
    assert d.source == "Process_A"
    assert d.target == "Process_B"


# ---------------------------------------------------------------------------
# 3. Rule → Cube
# ---------------------------------------------------------------------------
def test_rule_references_cube():
    payload = {
        "rules": [
            _rule("Cube_A", ("Cube_B",), statement="['X']=N:DB('Cube_B',...);"),
        ],
    }
    result = analyze_snapshot(payload, "snap")

    assert len(result.dependencies) == 1
    d = result.dependencies[0]
    assert d.kind == DependencyKind.RULE_REFERENCES_CUBE
    assert d.source == "Cube_A"
    assert d.target == "Cube_B"


def test_rule_from_dict():
    # 也支持 dict 形态的 rule 条目
    payload = {
        "rules": [
            {"cube": "Cube_A", "referenced_cubes": ["Cube_B"]},
        ],
    }
    result = analyze_snapshot(payload, "snap")
    assert result.dependencies[0].target == "Cube_B"


# ---------------------------------------------------------------------------
# 4. 多个 Process 全部被分析
# ---------------------------------------------------------------------------
def test_multiple_processes_all_analyzed():
    payload = {
        "processes": [
            _process("P_1", "CellPutN(1, 'Cube_A', 'd', 'm');"),
            _process("P_2", "CellPutN(2, 'Cube_B', 'd', 'm');"),
            _process("P_3", "CellGetN('Cube_C', 'd', 'm');"),
        ],
    }
    result = analyze_snapshot(payload, "snap")

    # 三个 process 都产出了 Dependency，且都体现在统计中
    assert result.statistics["analyzed_process_count"] == 3
    sources = {d.source for d in result.dependencies}
    assert sources == {"P_1", "P_2", "P_3"}


# ---------------------------------------------------------------------------
# 5. 空 Snapshot
# ---------------------------------------------------------------------------
def test_empty_snapshot_returns_valid_result():
    result = analyze_snapshot({"processes": [], "rules": []}, "snap-empty")

    assert result.snapshot_id == "snap-empty"
    assert result.dependencies == ()
    assert result.statistics["process_count"] == 0
    assert result.statistics["rule_count"] == 0
    assert result.statistics["dependency_count"] == 0


def test_missing_keys_treated_as_empty():
    result = analyze_snapshot({}, "snap")
    assert result.dependencies == ()
    assert result.statistics["process_count"] == 0


# ---------------------------------------------------------------------------
# 6. 未知对象正常跳过
# ---------------------------------------------------------------------------
def test_unknown_objects_skipped():
    payload = {
        "processes": [_process("P", "CellPutN(1, 'Cube_A', 'd', 'm');")],
        "rules": [],
        "applications": [{"name": "App1"}],
        "worksheets": [{"name": "Sheet1"}],
        "cubes": ["Cube_A"],
        "dimensions": ["Dim_X"],
    }
    result = analyze_snapshot(payload, "snap")

    # 未知对象不导致崩溃，也不产出依赖
    assert len(result.dependencies) == 1
    assert result.dependencies[0].source == "P"


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------
def test_determinism():
    payload = {
        "processes": [
            _process("P_A", "CellPutN(1, 'Cube_Z', 'd', 'm');ExecuteProcess('P_B', 'pYear', '2024');"),
            _process("P_B", "CellPutN(2, 'Cube_A', 'd', 'm');"),
        ],
        "rules": [_rule("Cube_X", ("Cube_A", "Cube_B"))],
    }
    r1 = analyze_snapshot(payload, "snap")
    r2 = analyze_snapshot(payload, "snap")

    assert r1 == r2
    # ordering 也稳定
    assert [d.target for d in r1.dependencies] == [d.target for d in r2.dependencies]


# ---------------------------------------------------------------------------
# 8. Snapshot immutability
# ---------------------------------------------------------------------------
def test_snapshot_not_modified():
    payload = {
        "processes": [_process("P", "CellPutN(1, 'Cube_A', 'd', 'm');")],
        "rules": [],
    }
    before = {k: v for k, v in payload.items()}
    before_processes = list(payload["processes"])

    analyze_snapshot(payload, "snap")

    # payload 顶层键不变
    assert set(payload.keys()) == set(before.keys())
    # process 条目对象未被替换（仍是同一批 Domain Process）
    assert payload["processes"] == before_processes
    # 具体 process 内容不变
    assert payload["processes"][0].name == "P"
    assert payload["processes"][0].code == "CellPutN(1, 'Cube_A', 'd', 'm');"


# ---------------------------------------------------------------------------
# 9. Statistics
# ---------------------------------------------------------------------------
def test_statistics():
    payload = {
        "processes": [
            _process("P_1", "CellPutN(1, 'Cube_A', 'd', 'm');"),
            _process("P_2", "CellGetN('Cube_B', 'd', 'm');"),
        ],
        "rules": [_rule("Cube_X", ("Cube_A",))],
    }
    result = analyze_snapshot(payload, "snap")

    stats = result.statistics
    assert stats["process_count"] == 2
    assert stats["rule_count"] == 1
    assert stats["analyzed_process_count"] == 2
    assert stats["analyzed_rule_count"] == 1
    assert stats["dependency_count"] == 3  # 2 process + 1 rule
    assert stats["dependency_by_kind"][DependencyKind.PROCESS_WRITES_CUBE.value] == 1
    assert stats["dependency_by_kind"][DependencyKind.PROCESS_READS_CUBE.value] == 1
    assert stats["dependency_by_kind"][DependencyKind.RULE_REFERENCES_CUBE.value] == 1


def test_skipped_object_count():
    # 纯字符串 process 条目无法 normalize → 计入 skipped
    payload = {
        "processes": ["not_a_process_object"],
        "rules": [],
    }
    result = analyze_snapshot(payload, "snap")
    assert result.statistics["skipped_object_count"] == 1
    assert result.statistics["analyzed_process_count"] == 0


# ---------------------------------------------------------------------------
# 10. Evidence 保留
# ---------------------------------------------------------------------------
def test_evidence_preserved():
    payload = {
        "processes": [
            _process("P", "CellPutN(100, 'Cube_A', '2024', 'Measure');"),
        ],
    }
    result = analyze_snapshot(payload, "snap")

    dep = result.dependencies[0]
    assert dep.references
    ref = dep.references[0]
    assert ref.operation == "CellPutN"
    assert ref.source == "P"
    assert ref.target == "Cube_A"
    assert ref.evidence["target_cube_expr"] == "'Cube_A'"


# ---------------------------------------------------------------------------
# 附加：dict 形态 process（四段代码）也支持
# ---------------------------------------------------------------------------
def test_process_from_four_segment_dict():
    payload = {
        "processes": [
            {
                "name": "P_Dict",
                "prolog": "vCube = 'Cube_A';",
                "metadata": "",
                "data": "CellPutN(1, vCube, '2024', 'Measure');",
                "epilog": "",
                "parameters": [{"name": "pYear"}],
            },
        ],
    }
    result = analyze_snapshot(payload, "snap")
    assert result.dependencies[0].source == "P_Dict"
    assert result.dependencies[0].target == "Cube_A"


def test_analysis_module_has_no_forbidden_dependency():
    import ast
    import tm1_suite.analysis.assembly as aa

    with open(aa.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy", "networkx", "neo4j"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            assert not mod.startswith("tm1_suite.snapshot"), "assembly 不应依赖 snapshot store"
            assert not mod.startswith("tm1_suite.store"), "assembly 不应依赖 store"
            assert not mod.startswith("tm1_suite.api"), "assembly 不应依赖 api"
