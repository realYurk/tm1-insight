"""TM1 Insight Lineage Engine v1。

基于 Dependency（Direct）计算 Transitive Lineage，回答「一个对象的上游 / 下游
有哪些」以及「为什么存在这条 Lineage」（通过 path 追溯）。

```text
    Reference（语法事实）
        ↓ 语义解释
    Dependency（语义层：source depends_on target，Direct）
        ↓ 传递闭包（本包 engine.py）
    Lineage（source → target 的传递可达关系，含 path / depth）
```

本包**不实现**：Impact Analysis / Model Health / Snapshot Compare /
Change Intelligence / Graph DB（NetworkX / Neo4j）/ AI / RAG。
"""
from .engine import (
    LineageEngine,
    build_lineage,
    get_downstream,
    get_upstream,
)

__all__ = [
    "LineageEngine",
    "build_lineage",
    "get_downstream",
    "get_upstream",
]
