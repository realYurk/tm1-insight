"""TM1 Insight Snapshot Model Object Schema。

定义 Snapshot payload 的 **canonical（规范化）对象结构**，让 Snapshot 成为
「TM1 模型某一时刻的标准化事实快照」。

与 Domain Model 的区别（重要，不要混为一谈）：

- **Domain Model**（``domain/model.py``）：TM1 Insight 内部的语义对象
  （``Process`` / ``Rule`` / ``Cube`` / ``Dimension``），用 ``dataclass(frozen=True)``
  表达，可直接持有任意 Python 类型（tuple / Enum / 嵌套对象）。
- **Snapshot Object Schema**（本模块）：这些对象**在 Snapshot 文件中如何持久化**
  的契约。必须可序列化、稳定、可版本化、与 Python 实现细节解耦，
  未来 Collector 可直接生成、其他语言也能理解。

因此本模块**不**把 ``dataclasses.asdict()`` 直接当 Schema，而是显式定义：

1. **TypedDict 契约**（``ProcessPayload`` / ``RulePayload`` / ``CubePayload`` /
   ``DimensionPayload``）——文档化对象结构，运行时零成本。
2. **Validator**（``validate_snapshot_payload``）——边界校验，只检查「形状/类型」，
   不做 TM1 语义校验（不检查 cube 是否真实存在、process 是否可执行、rule 是否语法正确）。
3. **序列化辅助**（``to_payload_dict`` / ``process_to_payload`` 等）——把 Domain 对象
   转成纯 JSON 类型（string/number/boolean/null/array/object），排除 Python 专属类型
   （tuple / NamedTuple / Enum / dataclass / Path / datetime）。

关于 schema_version（避免两套版本体系）：

- ``snapshot/store.py`` 已定义 ``SUPPORTED_SCHEMA_VERSION = 1``，它描述的是
  **Snapshot persistence contract version**（整个快照落盘契约的版本），
  放在 ``SnapshotRecord``（Metadata）中。
- 因此 **payload 内不再放置第二份 schema_version**。本模块定义的 payload
  对象结构是 schema_version=1 契约的一部分。未来对象结构演进时，递增
  ``SUPPORTED_SCHEMA_VERSION`` 即可，不产生冲突的版本号。

本模块**不**引入 Pydantic / JSON Schema 外部依赖 / Marshmallow / protobuf /
Avro / ORM / migration framework，只用 stdlib。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence, TypedDict

from tm1_insight.snapshot.store import SUPPORTED_SCHEMA_VERSION

__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "ProcessPayload",
    "RulePayload",
    "CubePayload",
    "DimensionPayload",
    "SnapshotPayload",
    "SnapshotSchemaError",
    "validate_snapshot_payload",
    "process_to_payload",
    "rule_to_payload",
    "cube_to_payload",
    "dimension_to_payload",
    "to_payload_dict",
]


# ---------------------------------------------------------------------------
# TypedDict 契约（文档化对象结构，运行时零成本）
# ---------------------------------------------------------------------------

class ProcessPayload(TypedDict, total=False):
    """一个 TI Process 在 Snapshot 中的结构化形态。

    Process 保存结构化 TI（四段），而非单一 ``code`` 字符串——因为 TM1 TI Process
    本身具有 Prolog/Metadata/Data/Epilog/Parameters 语义，Parser 正是按这些语义工作。
    """

    name: str
    parameters: Sequence[dict]            # [{"name": "pCube"}, ...]
    prolog: str
    metadata: str
    data: str
    epilog: str


class RulePayload(TypedDict, total=False):
    """一个 Rule 在 Snapshot 中的形态（支持 RULE_REFERENCES_CUBE 依赖引擎）。"""

    cube: str
    statement: str
    referenced_cubes: Sequence[str]


class CubePayload(TypedDict, total=False):
    """一个 Cube 在 Snapshot 中的形态（第一阶段只保留分析真正需要的字段）。"""

    name: str
    dimensions: Sequence[str]              # 有序维度名
    rules: Sequence[str]                   # 规则语句文本（轻量，不做语义解析）


class DimensionPayload(TypedDict, total=False):
    """一个 Dimension 在 Snapshot 中的形态（轻量，不承载完整 Hierarchy/Element）。"""

    name: str
    elements: Sequence[str]
    subsets: Sequence[str]


class SnapshotPayload(TypedDict, total=False):
    """Snapshot payload 的顶层结构（规范化形态）。"""

    processes: Sequence[dict]
    rules: Sequence[dict]
    cubes: Sequence[dict]
    dimensions: Sequence[dict]


# ---------------------------------------------------------------------------
# Validator（边界校验，不做 TM1 语义校验）
# ---------------------------------------------------------------------------

class SnapshotSchemaError(Exception):
    """Snapshot payload 不符合 Schema（形状/类型错误）。

    不是 TM1 语义错误（cube 不存在、process 不可执行等不在此列）。
    """


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_str_list(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and all(_is_str(x) for x in v)


def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def validate_snapshot_payload(payload: Any) -> None:
    """校验一个 Snapshot payload 是否符合 canonical Schema。

    只校验「形状 / 类型」，不校验「语义」：

    校验（是）：
    - 顶层是 object/dict
    - processes/rules/cubes/dimensions 若是 array，则逐个校验
    - Process.name 存在且为 string；parameters 是 array 且每项有 string name；
      prolog/metadata/data/epilog 是 string
    - Rule.cube / referenced_cubes（string array）
    - Cube.name / dimensions（string array）
    - Dimension.name / elements / subsets（string array）

    不校验（否）：
    - cube / dimension 是否真实存在
    - process 是否可执行
    - rule 语法是否正确

    :raises SnapshotSchemaError: 形状或类型不合法时。
    """
    if not _is_obj(payload):
        raise SnapshotSchemaError("payload 必须是 object/dict")

    for key in ("processes", "rules", "cubes", "dimensions"):
        if key in payload and payload[key] is not None and not isinstance(
            payload[key], (list, tuple)
        ):
            raise SnapshotSchemaError(f"顶层字段 {key!r} 必须是 array")

    for proc in payload.get("processes") or []:
        _validate_process(proc)

    for rule in payload.get("rules") or []:
        _validate_rule(rule)

    for cube in payload.get("cubes") or []:
        _validate_cube(cube)

    for dim in payload.get("dimensions") or []:
        _validate_dimension(dim)


def _validate_process(proc: Any) -> None:
    if not _is_obj(proc):
        raise SnapshotSchemaError("process 必须是 object/dict")
    if "name" not in proc:
        raise SnapshotSchemaError("process 缺少 name")
    if not _is_str(proc["name"]):
        raise SnapshotSchemaError("process.name 必须是 string")
    if "parameters" in proc and proc["parameters"] is not None:
        if not isinstance(proc["parameters"], (list, tuple)):
            raise SnapshotSchemaError("process.parameters 必须是 array")
        for p in proc["parameters"]:
            if not _is_obj(p):
                raise SnapshotSchemaError("process.parameter 必须是 object")
            if "name" not in p or not _is_str(p["name"]):
                raise SnapshotSchemaError("process.parameter.name 必须是 string")
    for seg in ("prolog", "metadata", "data", "epilog"):
        if seg in proc and proc[seg] is not None and not _is_str(proc[seg]):
            raise SnapshotSchemaError(f"process.{seg} 必须是 string")


def _validate_rule(rule: Any) -> None:
    if not _is_obj(rule):
        raise SnapshotSchemaError("rule 必须是 object/dict")
    if "cube" in rule and not _is_str(rule["cube"]):
        raise SnapshotSchemaError("rule.cube 必须是 string")
    if "statement" in rule and rule["statement"] is not None and not _is_str(rule["statement"]):
        raise SnapshotSchemaError("rule.statement 必须是 string")
    if "referenced_cubes" in rule and rule["referenced_cubes"] is not None:
        if not _is_str_list(rule["referenced_cubes"]):
            raise SnapshotSchemaError("rule.referenced_cubes 必须是 string array")


def _validate_cube(cube: Any) -> None:
    if not _is_obj(cube):
        raise SnapshotSchemaError("cube 必须是 object/dict")
    if "name" in cube and not _is_str(cube["name"]):
        raise SnapshotSchemaError("cube.name 必须是 string")
    if "dimensions" in cube and cube["dimensions"] is not None:
        if not _is_str_list(cube["dimensions"]):
            raise SnapshotSchemaError("cube.dimensions 必须是 string array")
    if "rules" in cube and cube["rules"] is not None:
        if not _is_str_list(cube["rules"]):
            raise SnapshotSchemaError("cube.rules 必须是 string array")


def _validate_dimension(dim: Any) -> None:
    if not _is_obj(dim):
        raise SnapshotSchemaError("dimension 必须是 object/dict")
    if "name" in dim and not _is_str(dim["name"]):
        raise SnapshotSchemaError("dimension.name 必须是 string")
    if "elements" in dim and dim["elements"] is not None:
        if not _is_str_list(dim["elements"]):
            raise SnapshotSchemaError("dimension.elements 必须是 string array")
    if "subsets" in dim and dim["subsets"] is not None:
        if not _is_str_list(dim["subsets"]):
            raise SnapshotSchemaError("dimension.subsets 必须是 string array")


# ---------------------------------------------------------------------------
# 序列化辅助（Domain → 纯 JSON 类型，排除 Python 专属类型）
# ---------------------------------------------------------------------------

def process_to_payload(proc: Any) -> dict:
    """把 Domain Process 转为 ProcessPayload（纯 JSON 类型）。

    注意：Domain Process 只存了 ``code``（完整代码），没有四段拆分。
    这里把 ``code`` 整体放入 ``data`` 段（Parser 只 join 四段，顺序不影响解析），
    其余段置空。未来 Collector 若提供四段，直接按四段填充即可。
    """
    parameters = [
        {"name": p if isinstance(p, str) else p.get("name", "")}
        for p in (getattr(proc, "parameters", ()) or ())
    ]
    return {
        "name": proc.name,
        "parameters": parameters,
        "prolog": "",
        "metadata": "",
        "data": getattr(proc, "code", "") or "",
        "epilog": "",
    }


def rule_to_payload(rule: Any) -> dict:
    """把 Domain Rule 转为 RulePayload（纯 JSON 类型）。"""
    return {
        "cube": rule.cube,
        "statement": getattr(rule, "statement", "") or "",
        "referenced_cubes": list(getattr(rule, "referenced_cubes", ()) or ()),
    }


def cube_to_payload(cube: Any) -> dict:
    """把 Domain Cube 转为 CubePayload（纯 JSON 类型）。"""
    return {
        "name": cube.name,
        "dimensions": list(getattr(cube, "dimensions", ()) or ()),
        "rules": list(getattr(cube, "rules", ()) or ()),
    }


def dimension_to_payload(dim: Any) -> dict:
    """把 Domain Dimension 转为 DimensionPayload（纯 JSON 类型）。"""
    return {
        "name": dim.name,
        "elements": list(getattr(dim, "elements", ()) or ()),
        "subsets": list(getattr(dim, "subsets", ()) or ()),
    }


def to_payload_dict(
    *,
    processes: Sequence[Any] = (),
    rules: Sequence[Any] = (),
    cubes: Sequence[Any] = (),
    dimensions: Sequence[Any] = (),
) -> dict:
    """把一组 Domain 对象组装成顶层 SnapshotPayload（纯 JSON 类型）。

    不放入 schema_version（版本在 Metadata/SnapshotRecord 中）。
    """
    return {
        "processes": [process_to_payload(p) for p in processes],
        "rules": [rule_to_payload(r) for r in rules],
        "cubes": [cube_to_payload(c) for c in cubes],
        "dimensions": [dimension_to_payload(d) for d in dimensions],
    }
