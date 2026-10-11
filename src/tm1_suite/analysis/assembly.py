"""TM1 Insight Analysis Assembly。

把已有能力（Snapshot / Parser / Resolver / Dependency Engine）第一次组装起来，
回答一个核心问题：

> 给定一个 Snapshot，如何把其中的 TM1 Model Objects 组织起来，并调用已有
> Parser / Resolver / Dependency Engine，做一次确定性的模型分析？

架构定位：

```text
    Snapshot（snapshot/，不可变事实）
       ↓
    Analysis Assembly（本模块：load / normalize / dispatch / aggregate）
       ↓
    Parser → Resolver（parser.py / resolver.py，复用，不重写）
       ↓
    Reference（domain.model）
       ↓
    Dependency Engine（dependency/，复用，不重写）
       ↓
    AnalysisResult（本模块，轻量结果，内存对象，不持久化）
```

本模块是一个**装配层**，不是新的业务引擎：

- **不重新实现** hard_extract / parser / resolver / dependency 的任何逻辑。
- **不修改** Snapshot；分析结果是独立于 Snapshot 的派生物。
- **不持久化** 分析结果（不建 analysis DB / parquet / cache）。
- **确定性**：相同 Snapshot → 相同 AnalysisResult（依赖顺序、统计、排序稳定）。
- **纯内存**：不连接 TM1 Server、不扫描真实 DuckDB，只用小 fixture。

边界（对齐 domain/model.py 的既有定义）：

- Snapshot 是「某一时间点的模型事实」，Analysis 是「基于该 Snapshot 计算的
  分析结果」，二者相互独立，Analysis 绝不修改 Snapshot。
- 当前只分析 Dependency（把 Task 6 的 Dependency Engine 接到 Snapshot 上），
  不新增任何分析算法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from tm1_suite import resolver
from tm1_suite.dependency import DependencyEngine, build_process_dependencies
from tm1_suite.dependency import build_rule_dependencies as _build_rule_deps
from tm1_suite.domain.model import Dependency, Rule

__all__ = [
    "AnalysisResult",
    "analyze_snapshot",
    "AnalysisAssembly",
]


# ---------------------------------------------------------------------------
# AnalysisResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnalysisResult:
    """一次 Snapshot 分析的轻量结果（内存对象，不持久化）。

    字段刻意精简：只保留 snapshot_id + dependencies + statistics。
    Dependency 本身已持有 references/evidence（provenance），无需再复制
    Snapshot 全文 / 原始代码 / Parser AST。
    """

    snapshot_id: str
    dependencies: Sequence[Dependency] = ()
    statistics: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalization（把 Snapshot payload 转成现有引擎的输入，最小 adapter）
# ---------------------------------------------------------------------------

def _iter_items(payload: Mapping[str, Any], key: str) -> Iterable[Any]:
    """读取 payload 中某个对象集合（可能缺失 / 为 None）。"""
    items = payload.get(key) or []
    if not isinstance(items, (list, tuple)):
        return ()
    return items


def _normalize_process(item: Any) -> tuple[str, dict] | None:
    """把一个 process 条目 normalize 成 (name, ti_json)。

    支持的条目形态（最小 adapter，不建 ProcessV2/ProcessEntity 等复杂层）：

    1. Domain ``Process`` 对象（name / code / parameters）
    2. dict：``name`` + 四段代码 ``prolog/metadata/data/epilog``
    3. dict：``name`` + ``code``（完整代码，整体放入 data 段）

    不满足任一形态（如纯字符串、缺 name/code）→ 返回 None（由调用方计为 skipped）。
    """
    from tm1_suite.domain.model import Process

    if isinstance(item, Process):
        name = item.name
        code = item.code or ""
        parameters = item.parameters or ()
    elif isinstance(item, dict):
        name = item.get("name", "")
        if not name:
            return None
        parameters = item.get("parameters") or ()
        if any(k in item for k in ("prolog", "metadata", "data", "epilog")):
            code = ""  # 四段在下面组装
        else:
            code = item.get("code", "")
            if not code:
                return None
    else:
        return None

    if not name:
        return None

    # 构造 process_ti 需要的 ti_json（parameters 需为 [{"name": ...}] 形态）
    params = []
    for p in parameters:
        if isinstance(p, dict):
            params.append(p)
        else:
            params.append({"name": p})

    if isinstance(item, dict) and any(
        k in item for k in ("prolog", "metadata", "data", "epilog")
    ):
        ti_json = {
            "name": name,
            "prolog": item.get("prolog", "") or "",
            "metadata": item.get("metadata", "") or "",
            "data": item.get("data", "") or "",
            "epilog": item.get("epilog", "") or "",
            "parameters": params,
        }
    else:
        # code 整体放入 data 段（process_ti 只是 join 四段，顺序不影响解析）
        ti_json = {
            "name": name,
            "prolog": "",
            "metadata": "",
            "data": code,
            "epilog": "",
            "parameters": params,
        }
    return name, ti_json


def _normalize_rule(item: Any) -> Rule | None:
    """把一个 rule 条目 normalize 成 domain Rule。

    支持的条目形态：
    1. Domain ``Rule`` 对象（cube / statement / referenced_cubes）
    2. dict：``cube`` + ``referenced_cubes``（statement 可选）

    不满足 → 返回 None。
    """
    if isinstance(item, Rule):
        return item
    if isinstance(item, dict):
        cube = item.get("cube", "")
        if not cube:
            return None
        referenced = item.get("referenced_cubes") or ()
        if isinstance(referenced, str):
            referenced = (referenced,)
        return Rule(
            cube=cube,
            statement=item.get("statement", ""),
            referenced_cubes=tuple(referenced),
        )
    return None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _dependency_by_kind(deps: Sequence[Dependency]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in deps:
        counts[d.kind.value] = counts.get(d.kind.value, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

class AnalysisAssembly:
    """确定性的 Analysis Assembly（纯函数装配层，无外部依赖）。

    只负责 load / normalize / dispatch / aggregate，把已有 Parser / Resolver /
    Dependency Engine 接到 Snapshot payload 上，产出 AnalysisResult。
    """

    def analyze(self, payload: Mapping[str, Any], snapshot_id: str) -> AnalysisResult:
        """对一个 Snapshot payload 做一次确定性分析。

        :param payload: Snapshot 的 payload（通用 JSON Mapping）。
        :param snapshot_id: 快照标识，写入 AnalysisResult。
        :return: AnalysisResult（snapshot_id + dependencies + statistics）。
        """
        engine = DependencyEngine()
        deps: list[Dependency] = []

        process_items = list(_iter_items(payload, "processes"))
        rule_items = list(_iter_items(payload, "rules"))

        analyzed_process_count = 0
        analyzed_rule_count = 0
        skipped_object_count = 0

        # Process → Dependency（复用 resolver.resolve_process → dependency engine）
        for item in process_items:
            normalized = _normalize_process(item)
            if normalized is None:
                skipped_object_count += 1
                continue
            name, ti_json = normalized
            try:
                resolved = resolver.resolve_process(ti_json)
            except Exception:
                # 单个 Process 解析失败不应静默吞掉——向上抛，由调用方决定。
                raise
            deps.extend(engine.build_process_dependencies(name, resolved))
            analyzed_process_count += 1

        # Rule → Dependency（复用 domain Rule → dependency engine）
        for item in rule_items:
            rule = _normalize_rule(item)
            if rule is None:
                skipped_object_count += 1
                continue
            deps.extend(_build_rule_deps(rule))
            analyzed_rule_count += 1

        # 稳定排序（复用 dependency 的排序语义，保证确定性）
        from tm1_suite.dependency.engine import _sort_key
        deps.sort(key=_sort_key)

        statistics = {
            "process_count": len(process_items),
            "rule_count": len(rule_items),
            "analyzed_process_count": analyzed_process_count,
            "analyzed_rule_count": analyzed_rule_count,
            "skipped_object_count": skipped_object_count,
            "dependency_count": len(deps),
            "dependency_by_kind": _dependency_by_kind(deps),
        }

        return AnalysisResult(
            snapshot_id=snapshot_id,
            dependencies=tuple(deps),
            statistics=statistics,
        )


def analyze_snapshot(payload: Mapping[str, Any], snapshot_id: str = "") -> AnalysisResult:
    """便捷函数：对一个 Snapshot payload 做确定性分析（见 AnalysisAssembly）。"""
    return AnalysisAssembly().analyze(payload, snapshot_id)
