"""TM1 Insight Model Health Engine v1。

基于确定性证据（Model Object Inventory + Reference + Dependency）发现结构性
问题，产出 HealthFinding。不是评分系统，不是 AI 判断。

```text
    Model Object Inventory（Snapshot schema）
        +
    Reference（语法层事实）
        +
    Dependency（语义层 Direct）
        ↓
    Health Rules（确定性纯函数）
        ↓
    HealthFinding（kind / object / severity / reason / evidence）
```

核心原则：Absence of evidence is not evidence of absence —— 宁可少报，不误报。

本包**不实现**：Health Score / Dashboard / UI / REST API / CLI / Excel Report /
AI / RAG / Graph DB（NetworkX / Neo4j）/ Snapshot Compare / Change Intelligence /
自动修复 / 业务猜测。
"""
from .engine import (
    KIND_BROKEN_DEPENDENCY_TARGET,
    KIND_BROKEN_REFERENCE,
    HealthEngine,
    analyze_health,
)

__all__ = [
    "HealthEngine",
    "analyze_health",
    "KIND_BROKEN_REFERENCE",
    "KIND_BROKEN_DEPENDENCY_TARGET",
]
