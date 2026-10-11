"""hard_extract 模块的回归测试。

只锁定「当前真实行为」，不做未来预期。未来 Resolver / AST 实现后，
应更新这些测试以反映新行为。

覆盖能力：
- CellPutN（简单写点）
- CellGetN（读点 source cube）
- 变量赋值链（vCube -> 'Cube_A'）
- 嵌套 CellGet（dim 值里的 ←cube[dims]→measure）
- IF 条件栈保留
- ELSE 分支条件不混淆
- ExecuteProcess（识别 callee，不做参数传递）
- 多行函数调用（_find_multiline_call）
- Bedrock（copy/clear/zeroout/view.create）
- 日志区域剥离（strip_log_regions）
- 未解析变量（<var>）
- resolve_value depth 限制
"""
from __future__ import annotations

from tm1_insight.ingest import hard_extract as h


# ---------------------------------------------------------------------------
# Case 1：简单 CellPutN
# ---------------------------------------------------------------------------
def test_cellputn_basic(make_ti):
    ti = make_ti(data="CellPutN(100, 'Sales Detail', '2024', 'Jan', 'Revenue');")
    out = h.process_ti(ti)

    assert len(out["write_points"]) == 1
    wp = out["write_points"][0]
    assert wp["operation"] == "CellPutN"
    assert wp["target_cube"] == "Sales Detail"
    dim_values = [d["value"] for d in wp["dim_args"]]
    assert dim_values == ["2024", "Jan", "Revenue"]


# ---------------------------------------------------------------------------
# Case 2：CellGetN 识别 source cube
# ---------------------------------------------------------------------------
def test_cellgetn_source_cube(make_ti):
    ti = make_ti(data="vValue = CellGetN('Cost Detail', '2024', 'Jan', 'Amount');")
    out = h.process_ti(ti)

    assert len(out["read_points"]) == 1
    rp = out["read_points"][0]
    assert rp["operation"] == "CellGetN"
    assert rp["source_cube"] == "Cost Detail"


# ---------------------------------------------------------------------------
# Case 3：变量赋值链
# ---------------------------------------------------------------------------
def test_variable_assignment_chain(make_ti):
    ti = make_ti(
        prolog="vCube = 'Cube_A';",
        data="CellPutN(100, vCube, '2024', 'Measure');",
    )
    out = h.process_ti(ti)

    assert len(out["write_points"]) == 1
    assert out["write_points"][0]["target_cube"] == "Cube_A"


# ---------------------------------------------------------------------------
# Case 4：嵌套 CellGet（出现在维度实参里）
# ---------------------------------------------------------------------------
def test_nested_cellget_in_dim(make_ti):
    # 嵌套 CellGet 出现在 CellPutN 的维度实参位置，才会进入 dim_args
    ti = make_ti(
        data=(
            "CellPutN(100, 'Target Cube', "
            "CellGetN('Source Cube', '2024', 'Jan', 'Amount'), 'Measure');"
        )
    )
    out = h.process_ti(ti)

    wp = out["write_points"][0]
    assert wp["target_cube"] == "Target Cube"
    # 第一个维度实参解析为 ←Source Cube[2024, Jan]→Amount
    dim0 = wp["dim_args"][0]["value"]
    assert "Source Cube" in dim0
    assert dim0.startswith("←")


# ---------------------------------------------------------------------------
# Case 5：IF 条件栈保留
# ---------------------------------------------------------------------------
def test_if_condition_preserved(make_ti):
    ti = make_ti(
        data="IF(pYear @= '2024');\nCellPutN(100, 'Sales Detail', pYear, 'Measure');\nEndIF;"
    )
    out = h.process_ti(ti)

    assert len(out["write_points"]) == 1
    wp = out["write_points"][0]
    # 当前行为：条件栈以列表形式保留
    assert "pYear" in wp["conditions"][0]


# ---------------------------------------------------------------------------
# Case 6：ELSE 分支条件不混淆
# ---------------------------------------------------------------------------
def test_else_branch_conditions_isolated(make_ti):
    ti = make_ti(
        data=(
            "IF(pYear @= '2024');\n"
            "CellPutN(1, 'Cube_A', pYear, 'M');\n"
            "Else;\n"
            "CellPutN(2, 'Cube_B', pYear, 'M');\n"
            "EndIF;"
        )
    )
    out = h.process_ti(ti)

    assert len(out["write_points"]) == 2
    wp_if = next(w for w in out["write_points"] if w["target_cube"] == "Cube_A")
    wp_else = next(w for w in out["write_points"] if w["target_cube"] == "Cube_B")
    # IF 分支继承原始条件；ELSE 分支条件被取反为 NOT(...)，不再错误继承 IF 条件。
    assert wp_if["conditions"] == ["pYear @= '2024'"]
    assert wp_else["conditions"] == ["NOT(pYear @= '2024')"]


# ---------------------------------------------------------------------------
# Case 7：ExecuteProcess 识别 callee（不做参数传递）
# ---------------------------------------------------------------------------
def test_execute_process_callee(make_ti):
    ti = make_ti(data="ExecuteProcess('P_Child', 'pYear', '2024');")
    out = h.process_ti(ti)

    assert len(out["calls"]) == 1
    call = out["calls"][0]
    assert call["operation"] == "ExecuteProcess"
    assert call["callee"] == "P_Child"


# ---------------------------------------------------------------------------
# Case 8：多行函数调用
# ---------------------------------------------------------------------------
def test_multiline_call(make_ti):
    ti = make_ti(
        data=(
            "ExecuteProcess(\n"
            "    'P_Child',\n"
            "    'pYear', '2024'\n"
            ");"
        )
    )
    out = h.process_ti(ti)

    assert len(out["calls"]) == 1
    assert out["calls"][0]["callee"] == "P_Child"


# ---------------------------------------------------------------------------
# Case 9：Bedrock
# ---------------------------------------------------------------------------
def test_bedrock_copy_generates_read_and_write(make_ti):
    ti = make_ti(
        data=(
            "ExecuteProcess('}bedrock.cube.data.copy', "
            "'pLogOutput', 0, 'pSrcCube', 'Cube_Src', 'pTgtCube', 'Cube_Tgt', "
            "'pMappingToNewDims', '', 'pSuppressConsolidation', 0);"
        )
    )
    out = h.process_ti(ti)

    # 修复后：copy 用 pSrcCube/pTgtCube，source=源 cube、target=目标 cube，
    # 产生一条读（source）与一条写（target）。
    b = out["bedrock_calls"][0]
    assert b["bedrock_op"] == "copy"
    assert b["source_cube"] == "Cube_Src"
    assert b["target_cube"] == "Cube_Tgt"

    assert any(r["source_cube"] == "Cube_Src" for r in out["read_points"])
    assert any(w["target_cube"] == "Cube_Tgt" for w in out["write_points"])


def test_bedrock_clear_is_write(make_ti):
    ti = make_ti(
        data=(
            "ExecuteProcess('}bedrock.cube.data.clear', "
            "'pLogOutput', 0, 'pCube', 'Cube_A', 'pView', '', 'pFilter', '');"
        )
    )
    out = h.process_ti(ti)

    assert any(w["target_cube"] == "Cube_A" for w in out["write_points"])
    assert any(b["bedrock_op"] == "clear" for b in out["bedrock_calls"])


def test_bedrock_zeroout_is_write(make_ti):
    ti = make_ti(
        data=(
            "ExecuteProcess('}bedrock.cube.data.zeroout', "
            "'pLogOutput', 0, 'pCube', 'Cube_A', 'pView', '');"
        )
    )
    out = h.process_ti(ti)

    assert any(w["target_cube"] == "Cube_A" for w in out["write_points"])
    assert any(b["bedrock_op"] == "zeroout" for b in out["bedrock_calls"])


def test_bedrock_view_create_is_read(make_ti):
    ti = make_ti(
        data=(
            "ExecuteProcess('}bedrock.cube.view.create', "
            "'pLogOutput', 0, 'pCube', 'Cube_A', 'pView', 'v', 'pSubset', '');"
        )
    )
    out = h.process_ti(ti)

    assert any(r["source_cube"] == "Cube_A" for r in out["read_points"])
    assert any(b["bedrock_op"] == "view_create" for b in out["bedrock_calls"])


# ---------------------------------------------------------------------------
# Case 10：日志区域剥离
# ---------------------------------------------------------------------------
def test_log_region_stripped():
    code = (
        "#Region - Initialize Logging\n"
        "CellPutN(0, '}APQ Log', 'x', 'y', 'nProcessStartTime');\n"
        "#EndRegion - Initialize Logging\n"
        "CellPutN(100, 'Sales Detail', '2024', 'Jan', 'Revenue');\n"
    )
    stripped = h.strip_log_regions(code)

    assert "}APQ Log" not in stripped
    assert "Sales Detail" in stripped


def test_log_cube_not_parsed_as_business_write(make_ti):
    ti = make_ti(
        data="CellPutN(0, '}APQProcessExecutionLog', 'x', 'y', 'nProcessStartTime');"
    )
    out = h.process_ti(ti)

    # 日志 cube + 日志 measure 都会被过滤，最终无业务写点
    assert out["write_points"] == []


# ---------------------------------------------------------------------------
# Case 11：无法解析变量（<var>）
# ---------------------------------------------------------------------------
def test_unresolved_variable_marked(make_ti):
    ti = make_ti(data="CellPutN(100, vDynamicCube, '2024', 'Measure');")
    out = h.process_ti(ti)

    wp = out["write_points"][0]
    # 当前行为：无法解析的变量返回 <var> 占位
    assert wp["target_cube"] == "<vDynamicCube>"


# ---------------------------------------------------------------------------
# Case 12：resolve_value depth 限制
# ---------------------------------------------------------------------------
def test_resolve_value_depth_limit():
    # extract_assignments 的真实返回值是 {var: [expr, ...]}，值一定是 list。
    # 构造 10 层赋值链，验证 depth>8 时的截断行为。
    assignments = {f"v{i}": [f"v{i+1}"] for i in range(10)}
    assignments["v10"] = ["'END'"]

    result = h.resolve_value("v0", assignments)

    # 当前行为：超过 depth>8 后返回 <expr> 占位（具体锁定为 <v9>）
    assert result == "<v9>"


def test_resolve_value_cycle_guarded_by_depth():
    # 循环引用 v0->v1->v0 也应靠 depth 保护，返回 <v1> 而非无限递归
    assignments = {"v0": ["v1"], "v1": ["v0"]}
    result = h.resolve_value("v0", assignments)
    assert result == "<v1>"


# ---------------------------------------------------------------------------
# 补充：split_statements 保护引号内分号
# ---------------------------------------------------------------------------
def test_split_statements_protects_quoted_semicolon():
    stmts = h.split_statements("CellPutS('a;b', 'Cube', 'd', 'm');\nCellPutS('x', 'Cube', 'd', 'm');")
    # 第一句含引号内分号，不应被拆断
    assert len(stmts) == 2
    assert "'a;b'" in stmts[0][1]


# ---------------------------------------------------------------------------
# Task 10 新增：嵌套 IF / ELSE 条件栈正确切换
# ---------------------------------------------------------------------------
def test_nested_if_else_condition_stack(make_ti):
    ti = make_ti(
        data=(
            "IF(A);\n"
            "CellPutN(1, 'Cube_1', 'd', 'm');\n"
            "IF(B);\n"
            "CellPutN(2, 'Cube_2', 'd', 'm');\n"
            "Else;\n"
            "CellPutN(3, 'Cube_3', 'd', 'm');\n"
            "EndIF;\n"
            "Else;\n"
            "CellPutN(4, 'Cube_4', 'd', 'm');\n"
            "EndIF;\n"
            "CellPutN(5, 'Cube_5', 'd', 'm');\n"
        )
    )
    out = h.process_ti(ti)

    def conds(cube):
        return next(w["conditions"] for w in out["write_points"] if w["target_cube"] == cube)

    # statement_1 → A
    assert conds("Cube_1") == ["A"]
    # statement_2 → A + B
    assert conds("Cube_2") == ["A", "B"]
    # statement_3 → A + NOT(B)（内层 ELSE 只取反内层 B）
    assert conds("Cube_3") == ["A", "NOT(B)"]
    # statement_4 → NOT(A)（外层 ELSE 取反外层 A）
    assert conds("Cube_4") == ["NOT(A)"]
    # statement_5 → 无条件（EndIF 弹出后）
    assert conds("Cube_5") == []


def test_if_without_else_endif_clears_condition(make_ti):
    ti = make_ti(
        data=(
            "IF(A);\n"
            "CellPutN(1, 'Cube_1', 'd', 'm');\n"
            "EndIF;\n"
            "CellPutN(2, 'Cube_2', 'd', 'm');\n"
        )
    )
    out = h.process_ti(ti)
    by_cube = {w["target_cube"]: w["conditions"] for w in out["write_points"]}
    assert by_cube["Cube_1"] == ["A"]
    assert by_cube["Cube_2"] == []


# ---------------------------------------------------------------------------
# Task 10 新增：Bedrock copy 变量形式（pSrcCube/pTgtCube 经变量解析）
# ---------------------------------------------------------------------------
def test_bedrock_copy_variable_form(make_ti):
    ti = make_ti(
        prolog="sSource = 'Cube_Src'; sTarget = 'Cube_Tgt';",
        data=(
            "ExecuteProcess('}bedrock.cube.data.copy', "
            "'pLogOutput', 0, 'pSrcCube', sSource, 'pTgtCube', sTarget, "
            "'pMappingToNewDims', '', 'pSuppressConsolidation', 0);"
        )
    )
    out = h.process_ti(ti)

    b = out["bedrock_calls"][0]
    assert b["bedrock_op"] == "copy"
    assert b["source_cube"] == "Cube_Src"
    assert b["target_cube"] == "Cube_Tgt"
    assert any(r["source_cube"] == "Cube_Src" for r in out["read_points"])
    assert any(w["target_cube"] == "Cube_Tgt" for w in out["write_points"])
