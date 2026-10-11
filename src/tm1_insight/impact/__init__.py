"""TM1 Insight Impact Analysis Engine v1。

基于 Dependency（Direct）→ Lineage（Transitive）→ Impact（从指定 source 出发的
downstream 影响范围），回答「如果这个对象发生变化，沿已确认的依赖关系，哪些对象
会受影响」，并区分 direct / indirect、保留 path / depth / dependencies。

```text
    Reference（语法事实）
        ↓ 语义解释
    Dependency（语义层：source depends_on target，Direct）
        ↓ 传递闭包（lineage）
    Lineage（source → target 的传递可达关系，含 path / depth）
        ↓ 复用 get_downstream（本包 engine.py）
    Impact（direct / indirect，含 path / depth / dependencies）
```

本包**不实现**：upstream impact / Model Health / Snapshot Compare /
Change Intelligence / Graph DB（NetworkX / Neo4j）/ AI / RAG。
"""
from .engine import (
    ImpactEngine,
    analyze_impact,
    get_impact,
)

__all__ = [
    "ImpactEngine",
    "analyze_impact",
    "get_impact",
]
