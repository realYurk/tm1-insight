"""TM1 Insight Dependency Engine。

把 Parser → Resolver → Reference 的语法/解析层信息，提升为语义层
``Dependency``（source depends_on target），是本项目
「理解 TM1 Model」而非「画箭头工具」的关键一步。

架构定位：

    TM1 Code
       ↓
    Parser（parser.py / hard_extract.py）
       ↓
    ResolvedSymbol / CallResolution（resolver.py）
       ↓
    Reference（domain.model，语法层事实）
       ↓
    Dependency Engine（本包：语义判断 + 去重 + 稳定排序）
       ↓
    Dependency（domain.model，source depends_on target，可溯源）

本包**不实现**：Lineage / Impact / Health / Compare / Collector / Graph，
那些是 Dependency 之上的后续推导，属未来任务。

依赖方向单向：Dependency Engine → domain.model（复用 Reference/Dependency）；
不依赖 DuckDB / FastAPI / CLI / UI / SnapshotStore / TM1 Server / 网络 / AI。
"""
from .engine import (
    DependencyEngine,
    build_dependencies,
    build_process_dependencies,
    build_rule_dependencies,
)

__all__ = [
    "DependencyEngine",
    "build_dependencies",
    "build_process_dependencies",
    "build_rule_dependencies",
]
