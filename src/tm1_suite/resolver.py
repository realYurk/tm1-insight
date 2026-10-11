"""TM1 Symbol Resolver。

建立在 Parser 之上（``parser.parse_process`` / ``hard_extract`` 的原子能力），
负责回答：一个 TI 表达式 / 变量 / 参数 / Cube 符号，最终指向什么？

架构定位：

    TM1 Code
       ↓
    Parser（parser.py / hard_extract.py）
       ↓
    Resolver（本模块）
       ↓
    ResolvedSymbol（可解释的解析结果，带 kind / resolved / evidence）

设计原则：
- **纯函数、无 DuckDB 依赖**：不读取数据库，只依赖传入的 assignments / parameters。
- **复用现有语义，不发明新表示**：``<var>`` 仍表示 unresolved；``pXxx`` 前缀仍表示参数。
- **轻量可解释**：用 NamedTuple 表达 ResolvedSymbol，保留 expression/value/kind/resolved，
  为未来 Lineage 提供可追溯的 evidence，但不建立完整 Domain Model（那是 Task 5）。

本模块不搬 queries.py 里依赖 DuckDB 的 _var_source_map / _var_is_param / _ti_datasource_cube
（那些是「查询层对库内数据的解析」，属于未来 Lineage 迁移的范畴，不在本 Resolver 内）。
"""
from __future__ import annotations

from typing import NamedTuple

from tm1_suite.ingest import hard_extract
from tm1_suite.ingest.hard_extract import extract_assignments, resolve_value

__all__ = [
    "ResolvedSymbol",
    "CallResolution",
    "resolve_symbol",
    "resolve_assignments",
    "resolve_calls",
    "classify",
]


class ResolvedSymbol(NamedTuple):
    """一个符号的解析结果，可解释、可追溯。"""

    expression: str          # 原始表达式（如 "vCube" 或 "CellGetN(...)"）
    value: str               # 解析出的值（如 "Cube_A" 或 "<pCube>"）
    kind: str                # literal | variable | parameter | cellget | function | unresolved
    resolved: bool           # 是否解析成功（value 不含 <...> 占位）


class CallResolution(NamedTuple):
    """一次 ExecuteProcess / RunProcess 调用的解析结果，含实参绑定。"""

    callee: str                           # 被调用进程名（如 "P_Child" 或 "<pProc>"）
    arguments: dict[str, ResolvedSymbol]  # 形参名 → 实参解析结果（如 pCube → Cube_A）


def classify(expr: str, value: str, assignments: dict, parameters: set[str] | None) -> str:
    """根据表达式、解析值、赋值表、参数表，判定符号类别。

    类别判定规则（复用项目现有语义）：
    - 字面量（单引号/双引号包裹）→ literal
    - 解析失败（value 形如 <...>）→ 根据是否落到参数表区分 parameter / unresolved
    - 嵌套 CellGet（value 形如 ←cube[...]→measure）→ cellget
    - 其它函数调用 → function
    - 纯标识符且可解析 → variable
    """
    parameters = parameters or set()
    s = expr.strip()
    # 1) 字面量
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return "literal"
    # 2) 未解析（<...> 占位）：区分「落到参数」vs「未知」
    if value.startswith("<") and value.endswith(">"):
        inner = value[1:-1]
        if inner in parameters:
            return "parameter"
        return "unresolved"
    # 3) 嵌套 CellGet
    if value.startswith("←"):
        return "cellget"
    # 4) 函数调用（解析出 <func(...)> 或其它函数形态）
    if "(" in s and ")" in s:
        return "function"
    # 5) 纯变量，已解析成功
    return "variable"


def resolve_symbol(expr: str, assignments: dict, parameters: set[str] | None = None) -> ResolvedSymbol:
    """解析单个表达式/符号，返回可解释的 ResolvedSymbol。

    复用 hard_extract.resolve_value 作为底层解析，额外叠加 kind/resolved 分类。
    """
    value = resolve_value(expr, assignments)
    kind = classify(expr, value, assignments, parameters)
    resolved = not (value.startswith("<") and value.endswith(">"))
    return ResolvedSymbol(expression=expr, value=value, kind=kind, resolved=resolved)


def resolve_assignments(code: str) -> dict[str, list[str]]:
    """从 TI 代码提取赋值表（等价 hard_extract.extract_assignments）。

    返回 {变量名: [expr, ...]}（同一变量多处赋值可能有多个表达式）。
    """
    return extract_assignments(code)


def resolve_calls(calls: list[dict], assignments: dict,
                  parameters: set[str] | None = None) -> list[CallResolution]:
    """解析 TI 的调用列表，建立「实参 → 形参」绑定。

    输入是 hard_extract.extract_calls 的输出（每个 call 已含 callee + params{expr,value}）。
    这里把每个实参的 expr/value 提升为 ResolvedSymbol，形成可解释的绑定关系。

    不在此处实现完整跨 Process Lineage（那需要 callee 的形参表，属未来任务）。
    """
    results: list[CallResolution] = []
    for call in calls:
        callee = call.get("callee", "")
        args: dict[str, ResolvedSymbol] = {}
        for pname, p in (call.get("params") or {}).items():
            expr = p.get("expr", "")
            args[pname] = resolve_symbol(expr, assignments, parameters)
        results.append(CallResolution(callee=callee, arguments=args))
    return results


def resolve_process(ti_json: dict) -> dict:
    """一站式解析一个 TI：返回 Parser 结构化引用 + Resolver 增强的符号分类。

    结果 = parser.parse_process(ti_json) 的原始结构，外加：
    - "resolved_write_points"：每个写点的 target_cube/dim 值带 ResolvedSymbol 分类
    - "resolved_calls"：ExecuteProcess 调用的实参绑定（CallResolution 列表）

    保持原始字段不变，纯增量，便于未来 Lineage 消费而不破坏现有结构。
    """
    parsed = hard_extract.process_ti(ti_json)
    parameters = set(parsed.get("params") or [])
    assignments = resolve_assignments(
        "\n".join([
            ti_json.get("prolog", "") or "",
            ti_json.get("metadata", "") or "",
            ti_json.get("data", "") or "",
            ti_json.get("epilog", "") or "",
        ])
    )

    resolved_calls = resolve_calls(parsed.get("calls", []), assignments, parameters)

    # 写点的 target_cube 符号分类
    resolved_write_points = []
    for wp in parsed.get("write_points", []):
        resolved_write_points.append({
            **wp,
            "target_symbol": resolve_symbol(
                wp.get("target_cube_expr", ""), assignments, parameters
            ),
        })

    return {
        **parsed,
        "resolved_calls": resolved_calls,
        "resolved_write_points": resolved_write_points,
    }
