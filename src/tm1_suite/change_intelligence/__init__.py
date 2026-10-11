"""TM1 Insight Change Intelligence Engine v1。

把 Snapshot Compare（发生了什么变化）与 Impact / Lineage（变化影响什么）组装起来，
形成第一条完整的 ``Change → Impact`` 能力链。

```text
    Snapshot A          Snapshot B
         ↓                   ↓
    Compare（compare/）       ┐
         ↓                   │
    Change[]（added / removed / modified）
         ↓                   │
    提取 changed identity    │  复用 Compare 的 identity 语义
         ↓                   │
    get_upstream（lineage/） │  复用 Lineage 的 upstream 能力
         ↓                   │
    Affected Objects（依赖变化源的对象，去重 + 稳定排序）
```

本包**不实现**：UI / CLI / REST API / Graph DB / DuckDB / SnapshotStore 重构 /
Collector / Parser / Resolver / Health 集成 / AI / RAG / 新的图/Compare/Impact 算法。
"""
from .engine import (
    ChangeIntelligenceEngine,
    ChangeIntelligenceResult,
    analyze_changes,
)

__all__ = [
    "ChangeIntelligenceEngine",
    "ChangeIntelligenceResult",
    "analyze_changes",
]
