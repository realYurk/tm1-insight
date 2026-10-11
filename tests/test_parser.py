"""Parser Interface（parser.py）的最小回归测试。

验证：
- Interface 能解析简单 CellPut / CellGet / 变量 / IF / ExecuteProcess / Bedrock
- Interface 返回的数据与现有实现（hard_extract）完全一致
- 不重复 hard_extract 的 20 个 golden 用例，只锁定 Interface 的转发等价性。
"""
from __future__ import annotations

from tm1_suite import parser
from tm1_suite.ingest import hard_extract as h


def _ti(prolog="", metadata="", data="", epilog="", name="P"):
    return {
        "name": name,
        "prolog": prolog,
        "metadata": metadata,
        "data": data,
        "epilog": epilog,
        "parameters": [],
    }


# ---------------------------------------------------------------------------
# 行为等价性：Interface 输出 == hard_extract 输出
# ---------------------------------------------------------------------------
def test_parse_process_equals_process_ti():
    ti = _ti(
        prolog="vCube = 'Cube_A';",
        data="CellPutN(100, vCube, '2024', 'Measure');",
    )
    assert parser.parse_process(ti) == h.process_ti(ti)


def test_resolve_symbol_equals_resolve_value():
    assignments = {"vCube": ["'Cube_A'"]}
    assert parser.resolve_symbol("vCube", assignments) == h.resolve_value(
        "vCube", assignments
    )


def test_extract_assignments_reused_directly():
    code = "vCube = 'Cube_A';"
    assert parser.extract_assignments(code) == h.extract_assignments(code)


# ---------------------------------------------------------------------------
# Interface 能力逐项验证
# ---------------------------------------------------------------------------
def test_interface_parses_simple_cellput():
    out = parser.parse_process(_ti(data="CellPutN(100, 'Sales Detail', '2024', 'Revenue');"))
    assert len(out["write_points"]) == 1
    assert out["write_points"][0]["target_cube"] == "Sales Detail"


def test_interface_parses_cellget():
    out = parser.parse_process(_ti(data="v = CellGetN('Cost Detail', '2024', 'Amount');"))
    assert len(out["read_points"]) == 1
    assert out["read_points"][0]["source_cube"] == "Cost Detail"


def test_interface_resolves_variable():
    out = parser.parse_process(
        _ti(prolog="vCube = 'Cube_A';", data="CellPutN(1, vCube, 'd', 'm');")
    )
    assert out["write_points"][0]["target_cube"] == "Cube_A"


def test_interface_handles_if():
    out = parser.parse_process(
        _ti(data="IF(pYear @= '2024');\nCellPutN(1, 'Cube_A', pYear, 'm');\nEndIF;")
    )
    assert out["write_points"][0]["conditions"]


def test_interface_handles_execute_process():
    out = parser.parse_process(_ti(data="ExecuteProcess('P_Child', 'pYear', '2024');"))
    assert out["calls"][0]["callee"] == "P_Child"


def test_interface_handles_bedrock():
    out = parser.parse_process(
        _ti(
            data=(
                "ExecuteProcess('}bedrock.cube.data.clear', "
                "'pLogOutput', 0, 'pCube', 'Cube_A', 'pView', '');"
            )
        )
    )
    # 锁定当前真实行为：clear 用 pCube，能识别出 bedrock_op + 写入点
    assert any(b["bedrock_op"] == "clear" for b in out["bedrock_calls"])
    assert any(w["target_cube"] == "Cube_A" for w in out["write_points"])
