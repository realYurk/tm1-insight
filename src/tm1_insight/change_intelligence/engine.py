"""TM1 Change Intelligence Engine v1。

把 Snapshot Compare（发生了什么变化）与 Impact / Lineage（变化影响什么）
**组装**起来，形成 TM1 Insight 第一条完整的 ``Change → Impact`` 能力链：

```text
    Snapshot A                 Snapshot B
         ↓                          ↓
    Compare（compare/，复用）         ┐
         ↓                          │
    Change[]（added / removed / modified）
         ↓                          │
    提取 changed object identity    │  （复用 Compare 的 identity 语义，
         ↓                          │    不发明第二套）
    get_upstream（lineage/，复用）   │
         ↓                          │
    Affected Objects（依赖变化源的对象）
```

第一原则（对齐 AI_INSTRUCTIONS §6.2 / §16）：

- **复用 > 重写**：本模块不重新实现 Compare / Impact / Lineage / 图算法。
- **确定性 > 智能幻觉**：相同输入（无论顺序）产出相同、稳定排序、去重后的结果。
- **不猜测**：changed object 在 dependency graph 中找不到依赖者时，affected 为空，
  绝不根据同名 / 相似 / 业务经验伪造关系。

本模块**不实现**：UI / CLI / REST API / Graph DB / DuckDB / SnapshotStore 重构 /
Collector / Parser / Resolver / Health 集成 / AI / RAG / LLM / 新的图/Compare/Impact 算法。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from tm1_insight.compare import compare_snapshots
from tm1_insight.domain.model import Change, ChangeKind, Dependency, Impact, ImpactKind
from tm1_insight.lineage import get_upstream
from tm1_insight.lineage.engine import build_adjacency

__all__ = [
    "ChangeIntelligenceResult",
    "ChangeIntelligenceEngine",
    "analyze_changes",
]


# ---------------------------------------------------------------------------
# 内部：changed identity → affected（依赖者）的 upstream impact
# ---------------------------------------------------------------------------

def _changed_kinds() -> set[str]:
    """Change Intelligence 视为「变化」的 change_type（排除 UNCHANGED）。"""
    return {ChangeKind.ADDED.value, ChangeKind.REMOVED.value, ChangeKind.MODIFIED.value}


def _impact_from_upstream_lineage(changed_identity: str, lin: Any) -> Impact:
    """把 get_upstream 返回的一条 Lineage 提升为 Impact（source=变化源，target=受影响者）。

    ``get_upstream(dependencies, X)`` 返回的 Lineage：
    - ``source`` = 依赖 X 的对象（依赖者 Y）
    - ``target`` = X（被依赖方 / 变化源）
    - ``path`` = ``(Y, ..., X)``（从依赖者到变化源）

    要表达「X 变化 → Y 受影响」，需复用 Impact 既有语义
    （``source``=变化源、``target``=受影响对象），故把方向反转：
    ``Impact.source = X``、``Impact.target = Y``、``path = (X, ..., Y)``。
    """
    return Impact(
        source=changed_identity,
        target=lin.source,
        kind=ImpactKind.DIRECT if lin.depth == 1 else ImpactKind.INDIRECT,
        depth=lin.depth,
        path=tuple(reversed(lin.path)),
        dependencies=tuple(lin.dependencies),
    )


def _impact_sort_key(impact: Impact) -> tuple:
    """affected_objects 的稳定排序 key：target（受影响对象）→ source（变化源）→ depth。

    不依赖 set/dict 顺序 / hash / UUID / 时间。
    """
    return (impact.target, impact.source, impact.depth if impact.depth is not None else 0)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChangeIntelligenceResult:
    """Change Intelligence 的确定性结论（内存对象，不持久化）。

    字段：
    - ``before_snapshot_id`` / ``after_snapshot_id``：两个快照身份。
    - ``changes``：对象级变化列表（复用 Compare，仅 added / removed / modified）。
    - ``affected_objects``：去重后的受影响对象（每个受影响对象一条 Impact，
      稳定排序）。Impact 语义：``source``=变化源，``target``=受影响对象，
      ``path`` / ``depth`` 保留可解释性。
    - ``statistics``：added/removed/modified/unchanged/changed/affected 计数
      + affected_by_kind（direct/indirect）。
    """

    before_snapshot_id: str
    after_snapshot_id: str
    changes: Sequence[Change] = ()
    affected_objects: Sequence[Impact] = ()
    statistics: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def analyze_changes(
    before: Any,
    after: Any,
    dependencies: Iterable[Dependency] = (),
) -> ChangeIntelligenceResult:
    """组装 Compare + Impact，产出 Change Intelligence 结论。

    数据流：
    1. ``compare_snapshots(before, after)`` → 得到对象级 changes（复用 Compare，
       含 schema_version 校验）。
    2. 过滤出 ADDED / REMOVED / MODIFIED（UNCHANGED 不进入影响分析）。
    3. 对每个 changed object 的 identity（``Change.object_name``）做 upstream
       impact（复用 ``get_upstream``）——找出「依赖该变化源」的对象，即受影响者。
    4. 去重：同一受影响对象（``Impact.target``）只保留一条，确定性选取
       ``(source, depth)`` 字典序最小者；稳定排序。

    :param before: 前快照（payload 或带 schema_version 的 Snapshot 结构）。
    :param after: 后快照，形态同上。
    :param dependencies: 当前依赖关系集合（source depends_on target）。
        本模块只读取、不修改。
    :return: ChangeIntelligenceResult（changes / affected_objects / statistics）。
    """
    compare_result = compare_snapshots(before, after)
    changes = tuple(compare_result.changes)

    # 只把 added / removed / modified 视为 changed；unchanged 不进入影响分析
    changed_kinds = _changed_kinds()
    changed_changes = [c for c in changes if c.change_type in changed_kinds]

    deps = list(dependencies)

    # 性能优化：只构建一次邻接表，供所有 changed object 复用。
    # 之前对每个 changed object 都调用 get_upstream（内部各自重建邻接表），
    # 导致 O(changed × E) 的重复建图开销。现在构建一次并传入 _adj 复用。
    adj = build_adjacency(deps)

    # 收集所有 (changed identity → 依赖者) 的 Impact，再按受影响对象去重
    by_target: dict[str, Impact] = {}
    for change in changed_changes:
        identity = change.object_name
        if not identity:
            continue
        for lin in get_upstream(deps, identity, _adj=adj):
            impact = _impact_from_upstream_lineage(identity, lin)
            existing = by_target.get(impact.target)
            if existing is None:
                by_target[impact.target] = impact
            else:
                # 去重：同一受影响对象只保留 (source, depth) 字典序最小者（确定性）
                if (impact.source, impact.depth if impact.depth is not None else 0) < (
                    existing.source,
                    existing.depth if existing.depth is not None else 0,
                ):
                    by_target[impact.target] = impact

    affected = list(by_target.values())
    affected.sort(key=_impact_sort_key)

    # statistics
    added = sum(1 for c in changes if c.change_type == ChangeKind.ADDED.value)
    removed = sum(1 for c in changes if c.change_type == ChangeKind.REMOVED.value)
    modified = sum(1 for c in changes if c.change_type == ChangeKind.MODIFIED.value)
    unchanged = int(compare_result.statistics.get("unchanged_count", 0))
    affected_by_kind = {
        ImpactKind.DIRECT.value: sum(1 for a in affected if a.kind == ImpactKind.DIRECT),
        ImpactKind.INDIRECT.value: sum(1 for a in affected if a.kind == ImpactKind.INDIRECT),
    }

    statistics: dict[str, Any] = {
        "added_count": added,
        "removed_count": removed,
        "modified_count": modified,
        "unchanged_count": unchanged,
        "changed_count": len(changed_changes),
        "affected_count": len(affected),
        "affected_by_kind": affected_by_kind,
    }

    return ChangeIntelligenceResult(
        before_snapshot_id=compare_result.before_snapshot_id,
        after_snapshot_id=compare_result.after_snapshot_id,
        changes=changes,
        affected_objects=tuple(affected),
        statistics=statistics,
    )


class ChangeIntelligenceEngine:
    """Change Intelligence Engine v1（薄封装，纯函数）。

    只做「Compare + Impact 组装」，不新增 Compare / Impact / Lineage 能力。
    """

    def analyze(
        self,
        before: Any,
        after: Any,
        dependencies: Iterable[Dependency] = (),
    ) -> ChangeIntelligenceResult:
        """等价于 ``analyze_changes(before, after, dependencies)``。"""
        return analyze_changes(before, after, dependencies)
