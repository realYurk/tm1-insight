"""TM1 Insight Snapshot 基础设施。

本包提供 TM1 Model 快照的持久化基础（Metadata + Payload），
供未来 Snapshot Compare / Change Intelligence / Historical Analysis 使用。

当前只做「Snapshot Foundation」：
- 可识别（snapshot_id + instance + model + created_at + schema_version + content_hash）
- 不可变（每个快照独立目录，不覆盖、不改写）
- 可持久化 / 可读取 / 可校验（load 时显式报错，不静默吞损坏）

不做：TM1 Collector、Snapshot Compare、Change Intelligence、Dependency/Lineage/Impact。

架构定位：

    TM1 Server（未来 Collector）
         ↓
    Snapshot（本包：Metadata + Payload，JSON 持久化）
         ↓
    Domain Model（domain/，纯语义，与本包解耦）

依赖方向单向：CLI/API → Snapshot → 文件；本包不依赖 DuckDB / UI / API / domain。
"""
from .store import (
    SnapshotStore,
    SnapshotRecord,
    SnapshotLoadError,
    SUPPORTED_SCHEMA_VERSION,
)
from .schema import (
    SnapshotSchemaError,
    validate_snapshot_payload,
    process_to_payload,
    rule_to_payload,
    cube_to_payload,
    dimension_to_payload,
    to_payload_dict,
    ProcessPayload,
    RulePayload,
    CubePayload,
    DimensionPayload,
    SnapshotPayload,
)

__all__ = [
    "SnapshotStore",
    "SnapshotRecord",
    "SnapshotLoadError",
    "SUPPORTED_SCHEMA_VERSION",
    "SnapshotSchemaError",
    "validate_snapshot_payload",
    "process_to_payload",
    "rule_to_payload",
    "cube_to_payload",
    "dimension_to_payload",
    "to_payload_dict",
    "ProcessPayload",
    "RulePayload",
    "CubePayload",
    "DimensionPayload",
    "SnapshotPayload",
]
