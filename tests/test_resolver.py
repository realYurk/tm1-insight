"""Symbol Resolver（resolver.py）的回归测试。

覆盖：
1. direct literal
2. one-level variable
3. multi-level variable
4. unresolved variable
5. nested CellGet（现有 Parser 支持）
6. ExecuteProcess callee
7. ExecuteProcess argument binding
8. recursion / circular reference
9. depth limit
10. 与 Task 1 / Task 2 行为兼容
"""
from __future__ import annotations

from tm1_insight import resolver
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


# ---------------------------------------------------------------------------
# 1. direct literal
# ---------------------------------------------------------------------------
def test_resolve_direct_literal():
    s = resolver.resolve_symbol("'Cube_A'", {})
    assert s.value == "Cube_A"
    assert s.kind == "literal"
    assert s.resolved is True


# ---------------------------------------------------------------------------
# 2. one-level variable
# ---------------------------------------------------------------------------
def test_resolve_one_level_variable():
    assignments = {"vCube": ["'Cube_A'"]}
    s = resolver.resolve_symbol("vCube", assignments)
    assert s.value == "Cube_A"
    assert s.kind == "variable"
    assert s.resolved is True


# ---------------------------------------------------------------------------
# 3. multi-level variable
# ---------------------------------------------------------------------------
def test_resolve_multi_level_variable():
    assignments = {"v1": ["'Cube_A'"], "v2": ["v1"], "v3": ["v2"]}
    s = resolver.resolve_symbol("v3", assignments)
    assert s.value == "Cube_A"
    assert s.resolved is True


# ---------------------------------------------------------------------------
# 4. unresolved variable
# ---------------------------------------------------------------------------
def test_resolve_unresolved_variable():
    # vCube = pCube，pCube 未知 → 当前语义返回 <pCube>
    assignments = {"vCube": ["pCube"]}
    s = resolver.resolve_symbol("vCube", assignments)
    assert s.value == "<pCube>"
    assert s.kind == "unresolved"
    assert s.resolved is False


def test_resolve_unresolved_parameter_distinguished():
    # 若 pCube 在参数表里，则 kind 应为 parameter 而非 unresolved
    assignments = {"vCube": ["pCube"]}
    s = resolver.resolve_symbol("vCube", assignments, parameters={"pCube"})
    assert s.value == "<pCube>"
    assert s.kind == "parameter"


# ---------------------------------------------------------------------------
# 5. nested CellGet
# ---------------------------------------------------------------------------
def test_resolve_nested_cellget():
    assignments = {"v": ["CellGetN('Source Cube', '2024', 'Jan', 'Amount')"]}
    s = resolver.resolve_symbol("v", assignments)
    assert s.kind == "cellget"
    assert s.value.startswith("←")
    assert "Source Cube" in s.value


# ---------------------------------------------------------------------------
# 6. ExecuteProcess callee（经 resolve_calls）
# ---------------------------------------------------------------------------
def test_resolve_calls_callee():
    ti = _ti(data="ExecuteProcess('P_Child', 'pYear', '2024');")
    calls = h.extract_calls(
        h.strip_log_regions("\n".join([ti["prolog"], ti["metadata"], ti["data"], ti["epilog"]])),
        h.extract_assignments("\n".join([ti["prolog"], ti["metadata"], ti["data"], ti["epilog"]])),
    )
    resolved = resolver.resolve_calls(calls, {})
    assert len(resolved) == 1
    assert resolved[0].callee == "P_Child"


# ---------------------------------------------------------------------------
# 7. ExecuteProcess argument binding
# ---------------------------------------------------------------------------
def test_resolve_calls_argument_binding():
    ti = _ti(data="ExecuteProcess('P_Load', 'pCube', 'Cube_A', 'pYear', '2026');")
    full = "\n".join([ti["prolog"], ti["metadata"], ti["data"], ti["epilog"]])
    assignments = h.extract_assignments(full)
    calls = h.extract_calls(h.strip_log_regions(full), assignments)
    resolved = resolver.resolve_calls(calls, assignments)

    assert len(resolved) == 1
    args = resolved[0].arguments
    assert "pCube" in args and "pYear" in args
    assert args["pCube"].value == "Cube_A"
    assert args["pYear"].value == "2026"


# ---------------------------------------------------------------------------
# 8. recursion / circular reference
# ---------------------------------------------------------------------------
def test_resolve_circular_reference():
    assignments = {"v0": ["v1"], "v1": ["v0"]}
    s = resolver.resolve_symbol("v0", assignments)
    # 当前 depth 保护：返回 <v1>，resolved=False
    assert s.resolved is False
    assert s.value.startswith("<")


# ---------------------------------------------------------------------------
# 9. depth limit
# ---------------------------------------------------------------------------
def test_resolve_depth_limit():
    assignments = {f"v{i}": [f"v{i+1}"] for i in range(10)}
    assignments["v10"] = ["'END'"]
    s = resolver.resolve_symbol("v0", assignments)
    # 当前行为：超过 depth>8 返回 <v9>
    assert s.value == "<v9>"
    assert s.resolved is False


# ---------------------------------------------------------------------------
# 10. 与 Task 1 / Task 2 行为兼容（resolve_process 增量增强，原始字段不变）
# ---------------------------------------------------------------------------
def test_resolve_process_preserves_parser_output():
    ti = _ti(
        prolog="vCube = 'Cube_A';",
        data="CellPutN(100, vCube, '2024', 'Measure');",
    )
    parsed = h.process_ti(ti)
    resolved = resolver.resolve_process(ti)

    # 原始字段完全保留（与 parser.process_ti 等价）
    assert resolved["name"] == parsed["name"]
    assert resolved["write_points"] == parsed["write_points"]
    assert resolved["read_points"] == parsed["read_points"]
    assert resolved["calls"] == parsed["calls"]
    # 增量字段存在
    assert "resolved_calls" in resolved
    assert "resolved_write_points" in resolved
    # 写点的 target 符号分类正确
    ws = resolved["resolved_write_points"][0]["target_symbol"]
    assert ws.value == "Cube_A"
    assert ws.kind == "variable"
