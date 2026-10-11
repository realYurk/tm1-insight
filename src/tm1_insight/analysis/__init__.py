"""TM1 Insight Analysis Assembly。

把已有能力（Snapshot / Parser / Resolver / Dependency Engine）第一次组装起来，
对某个 Snapshot 做一次确定性的模型分析。

架构定位：

    Snapshot（不可变事实）
       ↓
    Analysis Assembly（本包：load / normalize / dispatch / aggregate）
       ↓
    Parser → Resolver（复用）
       ↓
    Reference → Dependency Engine（复用）
       ↓
    AnalysisResult（轻量内存结果，不持久化）

本包是「装配层」，不是新的业务引擎。不重新实现 Parser / Resolver /
Dependency，不修改 Snapshot，不持久化分析结果，不连接 TM1 Server。

依赖方向单向：analysis → domain.model + parser/resolver + dependency；
不依赖 DuckDB / FastAPI / CLI / UI / SnapshotStore / TM1 Server / 网络 / AI。
"""
from .assembly import AnalysisAssembly, AnalysisResult, analyze_snapshot

__all__ = [
    "AnalysisAssembly",
    "AnalysisResult",
    "analyze_snapshot",
]
