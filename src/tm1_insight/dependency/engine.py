"""TM1 Dependency Engine。

把 Parser → Resolver → Reference 产生的语法/解析层信息，提升为
**语义层 Dependency**：

```text
    TM1 Code
       ↓
    Parser（parser.py / hard_extract.py）
       ↓
    ResolvedSymbol / CallResolution（resolver.py）
       ↓
    Reference（domain.model，语法层事实）
       ↓
    Dependency Engine（本模块，语义判断 + 聚合 + 去重 + 稳定排序）
       ↓
    Dependency（domain.model，source depends_on target）
```

Reference 与 Dependency 的边界（对齐 domain/model.py 的既有定义）：

- **Reference** 是语法层事实：代码里出现了对某对象的引用，携带
  operation / evidence，**不判定语义方向**。
- **Dependency** 是语义层结论：``source depends_on target``，用
  ``DependencyKind`` 表达语义类别、``confidence`` 表达可靠度，
  并用 ``references`` 溯源到原始 Reference（Explainability 基础）。

本模块的确定性约束：

- **纯函数**：不依赖 DuckDB / FastAPI / CLI / UI / SnapshotStore / TM1 Server /
  网络 / AI。相同输入 → 相同输出。
- **只消费解析结果**：输入是 ``resolver.resolve_process`` 的输出（或等价
  ``hard_extract.process_ti`` 结构）+ ``Rule`` 对象；不复制 queries.py 里
  依赖 DuckDB 的 ``_var_source_map`` / ``_var_is_param`` / ``_ti_datasource_cube``。
- **去重 + 稳定排序**：同一 (source, target, kind) 只产生一条 Dependency，
  但聚合所有 Reference；输出按稳定 key 排序，保证 deterministic。
- **不制造无法证明的关系**：目标无法解析（形如 ``<pCube>``）时不产出假依赖。

本模块**不实现** Lineage / Impact / Health / Compare / Collector / Graph。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

from tm1_insight.domain.model import (
    Dependency,
    DependencyKind,
    Reference,
    ReferenceKind,
    Rule,
)

__all__ = [
    "DependencyEngine",
    "build_dependencies",
    "build_process_dependencies",
    "build_rule_dependencies",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 写操作 → 对应 ReferenceKind（对齐 domain.model.ReferenceKind.CELL_PUT）
_WRITE_OPERATIONS = {"CellPutN", "CellPutS", "CellIncrementN", "CellIncrementS"}

# 读操作 → 对应 ReferenceKind（对齐 domain.model.ReferenceKind.CELL_GET）
_READ_OPERATIONS = {"CellGetN", "CellGetS"}

# 框架调用（bedrock）读/写点中的 operation 标签，来自 hard_extract._bedrock_cube_points
_BEDROCK_WRITE_OPS = {"BedrockCopy", "BedrockClear", "BedrockZeroout"}
_BEDROCK_READ_OPS = {"BedrockCopy", "BedrockViewCreate"}

# 高置信度阈值：目标由 Resolver 直接确定（字面量 / 已解析变量）。
_HIGH_CONFIDENCE = 1.0


# ---------------------------------------------------------------------------
# 辅助：把 process_ti / resolve_process 的点提升为 Reference
# ---------------------------------------------------------------------------

def _resolve_target(target: str) -> tuple[str, bool]:
    """判断解析出的目标是否确定。

    返回 (target, resolved)。resolved 为 False 表示 target 形如 ``<pCube>``
    等未解析占位，此时不得据此制造 Dependency。
    """
    t = (target or "").strip()
    if not t:
        return "", False
    if t.startswith("<") and t.endswith(">"):
        return "", False
    return t, True


def _ref_from_write_point(process_name: str, wp: dict) -> Reference | None:
    """把一个写点提升为 Reference（Process → Cube 的写引用）。"""
    target, resolved = _resolve_target(wp.get("target_cube", ""))
    if not resolved:
        return None
    operation = wp.get("operation", "")
    kind = ReferenceKind.CELL_PUT
    return Reference(
        kind=kind,
        source=process_name,
        target=target,
        operation=operation,
        evidence={
            "line": wp.get("line"),
            "conditions": list(wp.get("conditions", []) or []),
            "target_cube_expr": wp.get("target_cube_expr", ""),
            "dim_args": [
                {"expr": d.get("expr", ""), "value": d.get("value", "")}
                for d in (wp.get("dim_args") or [])
            ],
        },
    )


def _ref_from_read_point(process_name: str, rp: dict) -> Reference | None:
    """把一个读点提升为 Reference（Process → Cube 的读引用）。"""
    target, resolved = _resolve_target(rp.get("source_cube", ""))
    if not resolved:
        return None
    operation = rp.get("operation", "")
    return Reference(
        kind=ReferenceKind.CELL_GET,
        source=process_name,
        target=target,
        operation=operation,
        evidence={
            "dim_args": [
                {"expr": d.get("expr", ""), "value": d.get("value", "")}
                for d in (rp.get("dim_args") or [])
            ],
        },
    )


def _ref_from_call(process_name: str, call: dict) -> Reference | None:
    """把一个 ExecuteProcess/RunProcess 调用提升为 Reference（Process → Process）。"""
    callee, resolved = _resolve_target(call.get("callee", ""))
    if not resolved:
        return None
    # 过滤框架/系统调用（} 开头），只保留业务进程调用
    if callee.startswith("}"):
        return None
    return Reference(
        kind=ReferenceKind.PROCESS_CALL,
        source=process_name,
        target=callee,
        operation=call.get("operation", ""),
        evidence={
            "callee_expr": call.get("callee_expr", ""),
            "params": {
                pname: p.get("value", "")
                for pname, p in (call.get("params") or {}).items()
            },
        },
    )


def _ref_from_rule(rule: Rule, ref_cube: str) -> Reference | None:
    """把 Rule 中的一个跨 cube 引用提升为 Reference（Rule → Cube）。"""
    target, resolved = _resolve_target(ref_cube)
    if not resolved:
        return None
    return Reference(
        kind=ReferenceKind.RULE_REFERENCE,
        source=rule.cube,
        target=target,
        operation="RuleReference",
        evidence={"cube": rule.cube, "statement": rule.statement},
    )


# ---------------------------------------------------------------------------
# Dependency 聚合（去重 + 保留全部 references + 稳定排序）
# ---------------------------------------------------------------------------

def _dependency_key(dep: Dependency) -> tuple:
    """Dependency 的稳定去重/排序 key：source → kind → target。"""
    return (dep.source, dep.kind.value, dep.target)


def _sort_key(dep: Dependency) -> tuple:
    """输出的稳定排序 key。

    优先按语义类别分组，再按 source、target 字典序，保证确定性。
    """
    return (dep.kind.value, dep.source, dep.target)


def _aggregate(
    groups: dict[tuple[DependencyKind, str, str], list[Reference]],
) -> list[Dependency]:
    """把 (kind, source, target) → references 的聚合结果，转成有序 Dependency 列表。"""
    deps: list[Dependency] = []
    for (kind, source, target), refs in groups.items():
        deps.append(
            Dependency(
                kind=kind,
                source=source,
                target=target,
                confidence=_HIGH_CONFIDENCE,
                references=tuple(refs),
            )
        )
    deps.sort(key=_sort_key)
    return deps


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DependencyEngine:
    """确定性的 TM1 Dependency Engine（纯函数，无外部依赖）。

    消费 Parser/Resolver 的解析结果，产出 Dependency 集合。
    """

    def build_process_dependencies(self, process_name: str, parsed: dict) -> list[Dependency]:
        """从一个 Process 的解析结果（process_ti / resolve_process 输出）构建 Dependency。

        覆盖：
        - Process → Cube（写）：CellPutN/S、CellIncrementN/S、bedrock clear/copy/zeroout
        - Process → Cube（读）：CellGetN/S、bedrock copy/view_create
        - Process → Process：ExecuteProcess / RunProcess（callee 确定且非框架调用）

        不产出：目标未解析（``<pCube>``）的假依赖；跨进程参数传播。
        """
        groups: dict[tuple[DependencyKind, str, str], list[Reference]] = {}

        # 写点 → PROCESS_WRITES_CUBE
        for wp in parsed.get("write_points", []):
            ref = _ref_from_write_point(process_name, wp)
            if ref is None:
                continue
            key = (DependencyKind.PROCESS_WRITES_CUBE, process_name, ref.target)
            groups.setdefault(key, []).append(ref)

        # 读点 → PROCESS_READS_CUBE
        for rp in parsed.get("read_points", []):
            ref = _ref_from_read_point(process_name, rp)
            if ref is None:
                continue
            key = (DependencyKind.PROCESS_READS_CUBE, process_name, ref.target)
            groups.setdefault(key, []).append(ref)

        # 调用 → PROCESS_CALLS_PROCESS
        for call in parsed.get("calls", []):
            ref = _ref_from_call(process_name, call)
            if ref is None:
                continue
            key = (DependencyKind.PROCESS_CALLS_PROCESS, process_name, ref.target)
            groups.setdefault(key, []).append(ref)

        return _aggregate(groups)

    def build_rule_dependencies(self, rule: Rule) -> list[Dependency]:
        """从一个 Rule 构建 Dependency。

        只识别跨 cube 引用：``referenced_cubes`` 中的 cube 若 ≠ rule.cube，
        则生成 ``Rule(cube) depends_on Cube``。自身引用（ref == rule.cube）
        不生成自依赖。
        """
        groups: dict[tuple[DependencyKind, str, str], list[Reference]] = {}
        for ref_cube in rule.referenced_cubes:
            target, resolved = _resolve_target(ref_cube)
            if not resolved:
                continue
            if target == rule.cube:
                # 自身引用不算依赖（避免 Rule(Cube_A) depends_on Cube_A 假自依赖）
                continue
            ref = _ref_from_rule(rule, ref_cube)
            if ref is None:
                continue
            key = (DependencyKind.RULE_REFERENCES_CUBE, rule.cube, target)
            groups.setdefault(key, []).append(ref)
        return _aggregate(groups)


def build_process_dependencies(process_name: str, parsed: dict) -> list[Dependency]:
    """便捷函数：从一个 Process 解析结果构建 Dependency（见 DependencyEngine）。"""
    return DependencyEngine().build_process_dependencies(process_name, parsed)


def build_rule_dependencies(rule: Rule) -> list[Dependency]:
    """便捷函数：从一个 Rule 构建 Dependency（见 DependencyEngine）。"""
    return DependencyEngine().build_rule_dependencies(rule)


def build_dependencies(
    processes: Iterable[dict] | None = None,
    rules: Iterable[Rule] | None = None,
) -> list[Dependency]:
    """一站式构建 Dependency 集合。

    :param processes: 可迭代的 (process_name, parsed_dict) 元组，或含
        ``name`` + 解析字段（write_points/read_points/calls）的 dict。
        若元素是 dict，则用 ``dict["name"]`` 作为 source；否则视为 (name, parsed)。
    :param rules: 可迭代的 Rule 对象。
    :return: 稳定排序、去重后的 Dependency 列表。
    """
    engine = DependencyEngine()
    deps: list[Dependency] = []
    for item in processes or []:
        if isinstance(item, tuple):
            pname, parsed = item
        else:
            pname = item.get("name", "")
            parsed = item
        deps.extend(engine.build_process_dependencies(pname, parsed))
    for rule in rules or []:
        deps.extend(engine.build_rule_dependencies(rule))
    deps.sort(key=_sort_key)
    return deps
