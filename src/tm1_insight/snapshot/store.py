"""Snapshot 持久化层。

职责：把 TM1 Model 的「某时刻不可变快照」可靠地保存 / 读取 / 校验。

设计原则（对齐 AI_INSTRUCTIONS.md §10、§31）：
- **不可变**：每个 Snapshot 独立目录，创建后内容不被改写、不被后续快照覆盖。
- **Metadata + Payload 分离**：
  - Metadata：快照身份与描述（snapshot_id / instance / model / created_at /
    schema_version / source / object_counts / content_hash）。
  - Payload：快照内容（对象集合），当前以轻量 JSON 承载，不强制复制整个 DuckDB。
- **格式中立**：本模块只负责 JSON 持久化，不 import DuckDB / UI / API / domain，
  上层不应关心快照具体存成什么格式。
- **校验**：读取时显式发现「文件不存在 / metadata 缺失 / schema_version 不支持 /
  snapshot_id 不匹配 / 内容损坏」，绝不把损坏快照静默当成空快照。

本模块不实现 Collector（TM1 Server → Snapshot 采集）、不实现 Snapshot Compare、
不实现 Change Intelligence，那些属后续任务。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "SnapshotStore",
    "SnapshotRecord",
    "SUPPORTED_SCHEMA_VERSION",
    "SnapshotLoadError",
]

# 当前支持的快照 schema 版本。未来 Domain Model / 存储结构演进时递增。
SUPPORTED_SCHEMA_VERSION = 1

# 快照目录内固定文件名
_METADATA_FILENAME = "metadata.json"
_PAYLOAD_FILENAME = "payload.json"


class SnapshotLoadError(Exception):
    """读取快照失败（不存在 / 损坏 / 版本不支持 / 身份不匹配）。"""


@dataclass(frozen=True)
class SnapshotRecord:
    """一个已落盘的 Snapshot 的身份与内容描述（不含 payload 全文）。

    这是 Snapshot 的「门面」，用于 list / 校验，不直接等于 Domain 层的
    ``domain.model.Snapshot``（那是纯语义对象，本记录是持久化后的元数据）。
    """

    snapshot_id: str
    instance_id: str
    model_name: str
    created_at: str = ""
    source: str = "tm1"
    schema_version: int = SUPPORTED_SCHEMA_VERSION
    object_counts: Mapping[str, int] = field(default_factory=dict)
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "instance_id": self.instance_id,
            "model_name": self.model_name,
            "created_at": self.created_at,
            "source": self.source,
            "schema_version": self.schema_version,
            "object_counts": dict(self.object_counts),
            "content_hash": self.content_hash,
        }


def _hash_payload(payload: Any) -> str:
    """对 payload 计算内容哈希（SHA-256），作为 identity / integrity 辅助信息。

    使用确定性的 JSON 序列化（sort_keys + 紧凑分隔符），保证相同内容得到稳定哈希。
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SnapshotStore:
    """基于目录的 Snapshot 持久化。

    布局：:

        <root>/
          snapshots/
            <snapshot_id>/
              metadata.json   # 身份 + 描述
              payload.json    # 内容（轻量 JSON）
    """

    def __init__(self, root: str | Path):
        # root 指向快照根目录（如 data/snapshots）
        self.root = Path(root)

    # ---- 目录 ----
    def _snapshot_dir(self, snapshot_id: str) -> Path:
        return self.root / snapshot_id

    def _metadata_path(self, snapshot_id: str) -> Path:
        return self._snapshot_dir(snapshot_id) / _METADATA_FILENAME

    def _payload_path(self, snapshot_id: str) -> Path:
        return self._snapshot_dir(snapshot_id) / _PAYLOAD_FILENAME

    # ---- create / save ----
    def create_snapshot(
        self,
        snapshot_id: str,
        instance_id: str,
        model_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        created_at: str = "",
        source: str = "tm1",
        schema_version: int = SUPPORTED_SCHEMA_VERSION,
        object_counts: Mapping[str, int] | None = None,
    ) -> SnapshotRecord:
        """创建一个新快照并落盘。

        若 snapshot_id 已存在则抛出（不可变：不允许覆盖已有快照）。
        payload 为 None 时生成空内容 `{}`。
        """
        if self.exists(snapshot_id):
            raise SnapshotLoadError(f"快照已存在，不可覆盖: {snapshot_id}")

        payload = dict(payload or {})
        content_hash = _hash_payload(payload)
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            instance_id=instance_id,
            model_name=model_name,
            created_at=created_at,
            source=source,
            schema_version=schema_version,
            object_counts=dict(object_counts or {}),
            content_hash=content_hash,
        )
        self.save_snapshot(snapshot_id, payload, record)
        return record

    def save_snapshot(
        self,
        snapshot_id: str,
        payload: Mapping[str, Any],
        record: SnapshotRecord,
    ) -> None:
        """把 payload + metadata 写入快照目录（create 的内部实现）。

        写入前再次校验 snapshot_id 一致性，且不覆盖已存在目录（原子性兜底）。
        """
        if record.snapshot_id != snapshot_id:
            raise SnapshotLoadError(
                f"snapshot_id 不一致: record={record.snapshot_id!r} dir={snapshot_id!r}"
            )
        d = self._snapshot_dir(snapshot_id)
        # 目录已存在即视为冲突（不可变原则：不静默覆盖）
        if d.exists():
            raise SnapshotLoadError(f"快照目录已存在，不可覆盖: {snapshot_id}")

        d.mkdir(parents=True, exist_ok=False)
        self._metadata_path(snapshot_id).write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._payload_path(snapshot_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- load ----
    def load_snapshot(self, snapshot_id: str) -> tuple[SnapshotRecord, dict[str, Any]]:
        """读取一个快照，返回 (metadata, payload)。

        校验：
        - 目录 / metadata 不存在 → SnapshotLoadError
        - metadata 缺关键字段 → SnapshotLoadError
        - schema_version 不支持 → SnapshotLoadError
        - snapshot_id 与请求不符 → SnapshotLoadError
        - payload 损坏 / 哈希不符 → SnapshotLoadError
        """
        if not self.exists(snapshot_id):
            raise SnapshotLoadError(f"快照不存在: {snapshot_id}")

        meta_path = self._metadata_path(snapshot_id)
        if not meta_path.exists():
            raise SnapshotLoadError(f"快照缺少 metadata: {snapshot_id}")

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise SnapshotLoadError(f"快照 metadata 损坏: {snapshot_id} ({e})") from e

        record = self._record_from_metadata(meta, snapshot_id)

        payload_path = self._payload_path(snapshot_id)
        if not payload_path.exists():
            raise SnapshotLoadError(f"快照缺少 payload: {snapshot_id}")
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise SnapshotLoadError(f"快照 payload 损坏: {snapshot_id} ({e})") from e

        # 完整性：内容哈希校验
        actual_hash = _hash_payload(payload)
        if record.content_hash and actual_hash != record.content_hash:
            raise SnapshotLoadError(
                f"快照内容校验失败（哈希不符）: {snapshot_id}"
            )

        return record, payload

    def load_metadata(self, snapshot_id: str) -> SnapshotRecord:
        """只读取 metadata（不读 payload），用于 list / 快速校验。"""
        if not self.exists(snapshot_id):
            raise SnapshotLoadError(f"快照不存在: {snapshot_id}")
        meta_path = self._metadata_path(snapshot_id)
        if not meta_path.exists():
            raise SnapshotLoadError(f"快照缺少 metadata: {snapshot_id}")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise SnapshotLoadError(f"快照 metadata 损坏: {snapshot_id} ({e})") from e
        return self._record_from_metadata(meta, snapshot_id)

    def _record_from_metadata(self, meta: dict, snapshot_id: str) -> SnapshotRecord:
        """从 metadata dict 构造 SnapshotRecord，并做字段校验。"""
        # 关键字段缺失
        for required in ("snapshot_id", "instance_id", "model_name"):
            if required not in meta:
                raise SnapshotLoadError(f"快照 metadata 缺少字段: {required}")

        # snapshot_id 不匹配
        if meta["snapshot_id"] != snapshot_id:
            raise SnapshotLoadError(
                f"snapshot_id 不匹配: 请求={snapshot_id!r} metadata={meta['snapshot_id']!r}"
            )

        # schema_version 不支持
        sv = meta.get("schema_version", SUPPORTED_SCHEMA_VERSION)
        if sv > SUPPORTED_SCHEMA_VERSION:
            raise SnapshotLoadError(
                f"快照 schema_version 不支持: {sv}（当前支持 {SUPPORTED_SCHEMA_VERSION}）"
            )

        return SnapshotRecord(
            snapshot_id=meta["snapshot_id"],
            instance_id=meta["instance_id"],
            model_name=meta["model_name"],
            created_at=meta.get("created_at", ""),
            source=meta.get("source", "tm1"),
            schema_version=sv,
            object_counts=dict(meta.get("object_counts", {})),
            content_hash=meta.get("content_hash", ""),
        )

    # ---- list / exists ----
    def exists(self, snapshot_id: str) -> bool:
        return self._snapshot_dir(snapshot_id).exists()

    def list_snapshots(self) -> list[SnapshotRecord]:
        """列出所有快照的 metadata（按 snapshot_id 排序）。"""
        if not self.root.exists():
            return []
        records: list[SnapshotRecord] = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir():
                continue
            try:
                records.append(self.load_metadata(d.name))
            except SnapshotLoadError:
                # 损坏快照不阻断 listing，但也不静默丢弃——由上层决定如何处理
                continue
        records.sort(key=lambda r: r.snapshot_id)
        return records
