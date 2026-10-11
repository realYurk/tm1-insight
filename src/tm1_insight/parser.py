"""TM1 Parser 稳定入口（Adapter）。

这是一个非常薄的适配层，为未来的 Resolver / Lineage / Impact / Health
提供一个稳定的、最小化的 Parser 能力边界，让它们不再直接绑死
``tm1_insight.ingest.hard_extract`` 的内部实现。

设计原则：
- 不重写底层 Parser（``hard_extract.py`` 仍是唯一实现）。
- 只暴露「Parser 能提供什么能力」，不暴露 ``hard_extract`` 的全部内部函数。
- 行为与现有实现完全等价（本模块零解析逻辑，纯转发）。

当前暴露的能力（对应真实代码的两个语义层级）：

1. 进程级解析：``parse_process(ti_json)``
   把一个 TI 的 raw dict 解析为结构化引用：
   write_points / read_points / calls / bedrock_calls。
   这是 ``lineage.process_one`` 与 ``loader._insert_relations`` 的共同根基。

2. 符号解析：``resolve_symbol`` / ``extract_assignments``
   变量 → 字面量 / 嵌套 CellGet 的原子解析，被查询层反复调用。

其余内部 helper（split_statements / find_function_call / ...）不在此暴露，
它们属于 ``hard_extract.py`` 的实现细节。
"""
from __future__ import annotations

from tm1_insight.ingest.hard_extract import (
    extract_assignments,
    process_ti,
    resolve_value,
)

__all__ = ["parse_process", "resolve_symbol", "extract_assignments"]


def parse_process(ti_json: dict) -> dict:
    """解析一个 TI 的 raw dict，返回结构化引用（当前等价于 hard_extract.process_ti）。

    返回结构：
    {
        "name": str,
        "code_length": int,
        "business_code_length": int,
        "params": [str, ...],
        "write_points": [...],
        "read_points": [...],
        "calls": [...],
        "bedrock_calls": [...],
    }
    """
    return process_ti(ti_json)


def resolve_symbol(expr: str, assignments: dict) -> str:
    """解析一个表达式/符号（当前等价于 hard_extract.resolve_value）。

    变量 → 字面量 / 嵌套 CellGet（←cube[dims]→measure）/ 未解析（<var>）。
    """
    return resolve_value(expr, assignments)


# extract_assignments 直接复用（见 __all__），不额外包装。
