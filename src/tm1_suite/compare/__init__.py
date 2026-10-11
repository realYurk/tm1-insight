"""TM1 Insight Snapshot Compare Engine v1。

比较两个不可变 Snapshot 的 canonical payload，产出对象级、确定性、可解释的
变化结果（Change[] + 统计）。

```text
    Snapshot A            Snapshot B
         ↓                     ↓
    canonical payload    canonical payload
         ↓                     ↓
         └────── Compare ──────┘
                    ↓
    CompareResult（added / removed / modified / unchanged + statistics）
```

本包**不实现**：Change Intelligence / Impact integration / Health integration /
UI / REST API / CLI / Excel / Graph DB（NetworkX / Neo4j）/ AI / RAG / JSON Patch /
TI re-parser。
"""
from .engine import (
    CompareEngine,
    CompareError,
    CompareResult,
    compare_payloads,
    compare_snapshots,
)

__all__ = [
    "CompareEngine",
    "CompareError",
    "CompareResult",
    "compare_payloads",
    "compare_snapshots",
]
