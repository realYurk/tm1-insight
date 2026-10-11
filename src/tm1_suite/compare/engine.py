"""TM1 Snapshot Compare Engine v1。

比较两个不可变 Snapshot 的 canonical payload，产出**对象级、确定性、可解释**
的变化结果（Change 列表 + 统计）。

核心问题：两个 Snapshot 之间，哪些模型对象发生了确定性的结构变化？

架构定位：

```text
    Snapshot A（不可变）           Snapshot B（不可变）
         ↓                              ↓
    canonical payload              canonical payload
         ↓                              ↓
         └──────── Snapshot Compare（本模块）────────┘
                            ↓
                  Change[]（added / removed / modified / unchanged）
```

第一原则（对齐 AI_INSTRUCTIONS §6.2 / §10）：

- **Deterministic + Immutable + Pure**：绝不修改 A / B，绝不写回 SnapshotStore，
  绝不重新采集 TM1、重新解析 TI、重新构建 Dependency。
- **对象级 Compare**：不是「两个 JSON 不一样」，而是「哪些模型对象发生了确定性
  的结构变化」。
- **canonical compare**：字段顺序无关（用稳定序列化比较），不逐字符 diff。

本模块**不实现**：Change Intelligence / Impact integration / Health integration /
UI / REST API / CLI / Excel / Graph DB / NetworkX / AI / RAG / JSON Patch /
TI re-parser / Collector rewrite / Snapshot migration。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from tm1_suite.domain.model import Change, ChangeKind

__all__ = [
    "CompareResult",
    "CompareEngine",
    "compare_snapshots",
    "compare_payloads",
    "CompareError",
]


# ---------------------------------------------------------------------------
# 支持的 canonical collection（对齐 snapshot/schema.py 的 SnapshotPayload）
# ---------------------------------------------------------------------------

# (collection_key, object_type, identity 字段)
_COLLECTIONS: tuple[tuple[str, str, str], ...] = (
    ("processes", "process", "name"),
    ("cubes", "cube", "name"),
    ("dimensions", "dimension", "name"),
    ("rules", "rule", None),  # Rule 无 name，identity 特殊处理
)


class CompareError(Exception):
    """Snapshot Compare 输入非法（重复 identity / schema version 不匹配等）。"""


def _schema_version(obj: Any) -> Any:
    """从 Snapshot-level 对象中提取 schema_version（鸭子类型，不 import store）。

    支持携带 ``schema_version`` 的对象：
    - ``SnapshotRecord``（``.schema_version`` 属性）
    - dict（``["schema_version"]`` 键）

    无 schema_version 信息时返回 ``None``，由调用方决定是否降级为 payload-only。
    """
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get("schema_version")
    return getattr(obj, "schema_version", None)


def _require_same_schema_version(before: Any, after: Any) -> None:
    """若两个 Snapshot 都携带 schema_version 且不一致，抛 CompareError。

    若任一（或两者都）缺失 schema_version，则不校验（退化回 payload-only，
    因为 payload-only 本身无法得知版本）。这是「有版本信息就必须校验」的
    Contract Hardening：不同版本绝不静默比较。
    """
    before_sv = _schema_version(before)
    after_sv = _schema_version(after)

    if before_sv is not None and after_sv is not None and before_sv != after_sv:
        raise CompareError(
            f"不能比较 schema_version 不同的快照: {before_sv} != {after_sv}"
        )


# ---------------------------------------------------------------------------
# canonical 序列化（字段顺序无关）
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> str:
    """把一个对象做 canonical 序列化（字段顺序无关），返回稳定字符串。

    与 snapshot/store.py 的 ``_hash_payload`` 使用同一套确定性 JSON 序列化
    （sort_keys + 紧凑分隔符），保证相同内容（无论字段顺序）得到相同结果。
    list 保持有序（不转 set），尊重 schema 中 list 的顺序语义。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# identity 提取
# ---------------------------------------------------------------------------

def _identity(item: Any, object_type: str, id_field: str | None) -> str:
    """提取对象的稳定 identity。

    - process / cube / dimension：用 ``name`` 字段（dict 或 domain 对象）。
    - rule：schema 无 name，用 ``(cube, statement)`` 作为稳定身份。
    """
    if id_field is None:
        # Rule：identity = (cube, statement) 的稳定表达
        cube = item.get("cube", "") if isinstance(item, dict) else getattr(item, "cube", "")
        statement = (
            item.get("statement", "") if isinstance(item, dict) else getattr(item, "statement", "")
        )
        return _canonical((cube, statement))

    if isinstance(item, dict):
        return item.get(id_field, "")
    return getattr(item, id_field, "")


# ---------------------------------------------------------------------------
# 收集对象（含重复检测）
# ---------------------------------------------------------------------------

def _collect(
    payload: Mapping[str, Any], collection_key: str, object_type: str, id_field: str | None
) -> dict[str, Any]:
    """从 payload 收集某个 collection 的对象，按 identity 建索引。

    同一 identity 出现多次 → 抛 CompareError（明确失败，不静默覆盖）。
    """
    items = payload.get(collection_key) or []
    if not isinstance(items, (list, tuple)):
        items = []
    index: dict[str, Any] = {}
    for item in items:
        ident = _identity(item, object_type, id_field)
        if not ident:
            # 无 identity 的对象（如缺 name）无法 compare，明确跳过需谨慎——
            # 但缺 name 属 schema 非法，这里保守跳过（不做 CompareError，避免过度严格）。
            continue
        if ident in index:
            raise CompareError(
                f"collection {collection_key!r} 存在重复 identity: {ident!r}"
            )
        index[ident] = item
    return index


# ---------------------------------------------------------------------------
# CompareResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompareResult:
    """两个 Snapshot 的对象级差异结果（内存对象，不持久化）。

    字段：
    - ``before_snapshot_id`` / ``after_snapshot_id``：两个快照身份。
    - ``before_content_hash`` / ``after_content_hash``：内容哈希（辅助信息，
      不替代对象比较）。
    - ``changes``：有序 Change 列表（仅 added / removed / modified，不含 unchanged）。
    - ``statistics``：added_count / removed_count / modified_count / unchanged_count，
      以及按 object_type 的细分计数。
    """

    before_snapshot_id: str
    after_snapshot_id: str
    before_content_hash: str = ""
    after_content_hash: str = ""
    changes: Sequence[Change] = ()
    statistics: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 比较一个 collection
# ---------------------------------------------------------------------------

def _compare_collection(
    before_index: dict[str, Any],
    after_index: dict[str, Any],
    object_type: str,
) -> list[Change]:
    """比较一个 collection 的 before/after 索引，产出 Change 列表（不含 unchanged）。"""
    changes: list[Change] = []

    for ident in sorted(set(before_index) | set(after_index)):
        in_before = ident in before_index
        in_after = ident in after_index
        before_obj = before_index.get(ident)
        after_obj = after_index.get(ident)

        if in_before and not in_after:
            changes.append(Change(
                object_name=ident,
                change_type=ChangeKind.REMOVED.value,
                before=before_obj,
                after=None,
                object_type=object_type,
            ))
        elif not in_before and in_after:
            changes.append(Change(
                object_name=ident,
                change_type=ChangeKind.ADDED.value,
                before=None,
                after=after_obj,
                object_type=object_type,
            ))
        else:
            # 两边都有：比较 canonical content
            if _canonical(before_obj) != _canonical(after_obj):
                changes.append(Change(
                    object_name=ident,
                    change_type=ChangeKind.MODIFIED.value,
                    before=before_obj,
                    after=after_obj,
                    object_type=object_type,
                ))
            # 相同 → unchanged，不产出 Change（由 statistics 统计）

    return changes


# ---------------------------------------------------------------------------
# 排序（确定性）
# ---------------------------------------------------------------------------

def _sort_key(change: Change) -> tuple:
    """输出的稳定排序 key：object_type → identity → change_type。"""
    return (change.object_type, change.object_name, change.change_type)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CompareEngine:
    """Snapshot Compare Engine v1（薄封装，纯函数）。"""

    def compare(
        self,
        before_payload: Mapping[str, Any],
        after_payload: Mapping[str, Any],
        before_snapshot_id: str = "",
        after_snapshot_id: str = "",
    ) -> CompareResult:
        return compare_payloads(
            before_payload, after_payload, before_snapshot_id, after_snapshot_id
        )


def compare_payloads(
    before_payload: Mapping[str, Any],
    after_payload: Mapping[str, Any],
    before_snapshot_id: str = "",
    after_snapshot_id: str = "",
) -> CompareResult:
    """比较两个 canonical payload，产出对象级 CompareResult。

    :param before_payload: 变更前的 Snapshot payload（canonical schema）。
    :param after_payload: 变更后的 Snapshot payload（canonical schema）。
    :param before_snapshot_id: 前快照 ID（写入结果）。
    :param after_snapshot_id: 后快照 ID（写入结果）。
    :return: CompareResult（changes 稳定排序，statistics 含各计数）。
    """
    all_changes: list[Change] = []
    statistics: dict[str, Any] = {
        "added_count": 0,
        "removed_count": 0,
        "modified_count": 0,
        "unchanged_count": 0,
    }

    for collection_key, object_type, id_field in _COLLECTIONS:
        before_index = _collect(before_payload, collection_key, object_type, id_field)
        after_index = _collect(after_payload, collection_key, object_type, id_field)

        collection_changes = _compare_collection(before_index, after_index, object_type)
        all_changes.extend(collection_changes)

        # 统计（含 unchanged 计数）
        added = sum(1 for c in collection_changes if c.change_type == ChangeKind.ADDED.value)
        removed = sum(1 for c in collection_changes if c.change_type == ChangeKind.REMOVED.value)
        modified = sum(1 for c in collection_changes if c.change_type == ChangeKind.MODIFIED.value)
        unchanged = len(set(before_index) & set(after_index)) - modified

        statistics["added_count"] += added
        statistics["removed_count"] += removed
        statistics["modified_count"] += modified
        statistics["unchanged_count"] += unchanged
        statistics[f"{object_type}_added"] = added
        statistics[f"{object_type}_removed"] = removed
        statistics[f"{object_type}_modified"] = modified
        statistics[f"{object_type}_unchanged"] = unchanged

    all_changes.sort(key=_sort_key)

    return CompareResult(
        before_snapshot_id=before_snapshot_id,
        after_snapshot_id=after_snapshot_id,
        before_content_hash=_canonical(before_payload),
        after_content_hash=_canonical(after_payload),
        changes=tuple(all_changes),
        statistics=statistics,
    )


def compare_snapshots(before: Any, after: Any) -> CompareResult:
    """Snapshot-level 比较入口：比较两个 Snapshot。

    与 ``compare_payloads``（payload-only）的区别在于：本函数在能够获取
    schema_version 的路径上强制执行版本一致性校验（Contract Hardening）。

    :param before: 前快照。可为：
        - 纯 payload dict（仅 processes/rules/cubes/dimensions，无 schema_version）
          → 退化回 payload-only 比较（向后兼容）
        - 携带 schema_version 的快照结构（dict 含 schema_version 键，或
          ``SnapshotRecord`` 这类有 ``.schema_version`` 属性的对象）
    :param after: 后快照，形态同上。
    :raises CompareError: 当 before / after 都携带 schema_version 且不一致时。
    :return: CompareResult（对象级、确定性）。

    注意：对象收集只认 canonical collection 键（processes/rules/cubes/
    dimensions），额外的 meta 键（schema_version / snapshot_id 等）被忽略，
    因此「带 metadata 的完整快照」与「纯 payload」都能正确比较。
    """
    # 关键：任何明确携带 schema_version 的 Snapshot-level 比较必须校验一致。
    _require_same_schema_version(before, after)

    before_payload = before
    after_payload = after
    before_id = ""
    after_id = ""
    if isinstance(before, Mapping):
        before_id = before.get("snapshot_id", "") or ""
    if isinstance(after, Mapping):
        after_id = after.get("snapshot_id", "") or ""
    if not before_id and hasattr(before, "snapshot_id"):
        before_id = getattr(before, "snapshot_id", "") or ""
    if not after_id and hasattr(after, "snapshot_id"):
        after_id = getattr(after, "snapshot_id", "") or ""

    return compare_payloads(before_payload, after_payload, before_id, after_id)
