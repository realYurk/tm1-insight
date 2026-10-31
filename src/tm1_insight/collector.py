"""TM1 Collector：把 TM1 Server 的事实数据转换为 Canonical Snapshot Payload。

职责边界（严格单一）：

```text
    TM1 Server
       ↓ 事实采集（复用 tm1/client.py 的 TM1Client.fetch_*）
    raw dict（现有 exporter/loader 使用的形态）
       ↓ 字段映射 / 裁剪（本模块，纯转换，无网络/无副作用）
    Canonical Snapshot Payload（严格符合 snapshot/schema.py，Task 8）
       ↓
    validate_snapshot_payload()
```

Collector **只负责**「从 TM1 获取事实 → 转成 canonical payload」。它**不负责**：

- Parser / AST / Symbol Resolver / Dependency / Lineage / Impact / Health / Compare
- 解析 TI 代码语义（`referenced_cubes` 不在此解析，留待 Parser/Dependency Engine）
- UI / AI / Graph DB

设计原则：

- **可 mock / 可测试**：Collector 通过依赖注入接收一个 ``client``，任何提供了
  ``fetch_process`` / ``fetch_cube`` / ``fetch_dimension`` / ``list_all_names``
  的对象都可以（不强制是 TM1Client，不 import TM1py 到本模块）。
- **纯转换、无副作用**：不修改服务器、不落盘、无全局状态、无隐藏网络调用。
- **不伪造数据**：TM1 拿不到的字段保持 Schema 合法（空串 / 空数组），不猜测。
- **确定性**：相同 client 输入 → 相同 payload。

本模块不重构 SnapshotStore、不重构 ingest/exporter，只新增一个薄装配层。
"""

from __future__ import annotations

from typing import Any, Protocol

from tm1_insight.ingest.scope import split_by_scope
from tm1_insight.snapshot.schema import validate_snapshot_payload

__all__ = [
    "TM1Collector",
    "collect_snapshot",
    "CollectorClient",
]


# ---------------------------------------------------------------------------
# Client 协议（鸭子类型，不强制 TM1Client，便于 mock）
# ---------------------------------------------------------------------------

class CollectorClient(Protocol):
    """Collector 需要的最小 client 面（真实实现是 tm1.client.TM1Client）。

    只声明 Collector 实际用到的几个方法；任何实现这些方法的对象都能作为
    Collector 的数据源，从而让单元测试可以用 fake client，不连真实 TM1。
    """

    def list_all_names(self) -> dict[str, list[str]]: ...

    def fetch_process(self, tm1: Any, name: str) -> dict: ...

    def fetch_cube(self, tm1: Any, name: str) -> dict: ...

    def fetch_dimension(self, tm1: Any, name: str, is_system: bool) -> dict: ...


# ---------------------------------------------------------------------------
# 字段映射：raw dict → canonical schema
# ---------------------------------------------------------------------------

def _map_process(raw: dict) -> dict:
    """TM1Client.fetch_process 的 raw dict → ProcessPayload。

    raw.parameters 是 [{"name", "type", "default_value"}]，canonical 只要
    [{"name"}] 保留兼容；完整定义另存 parameter_definitions。Variables、
    DataSource、source_view 为可选增量字段；旧 payload 不要求补全。
    """
    parameters = [
        {"name": p.get("name", "")}
        for p in (raw.get("parameters") or [])
        if p.get("name")
    ]
    result = {
        "name": raw.get("name", ""),
        "parameters": parameters,
        "prolog": raw.get("prolog", "") or "",
        "metadata": raw.get("metadata", "") or "",
        "data": raw.get("data", "") or "",
        "epilog": raw.get("epilog", "") or "",
    }
    # Optional additions preserve old snapshots and distinguish missing from [].
    for key in ("variables", "datasource", "source_view"):
        if key in raw:
            result[key] = raw[key]
    result["parameter_definitions"] = [dict(p) for p in (raw.get("parameters") or []) if p.get("name")]
    return result


def _map_cube(raw: dict) -> dict:
    """TM1Client.fetch_cube 的 raw dict → CubePayload。

    raw.rules 是 string（完整规则文本），canonical CubePayload.rules 是
    Sequence[str]。有规则文本时包成单元素数组，否则空数组。
    """
    rules_text = raw.get("rules", "") or ""
    return {
        "name": raw.get("name", ""),
        "dimensions": list(raw.get("dimensions") or []),
        "rules": [rules_text] if rules_text.strip() else [],
    }


def _map_dimension(raw: dict) -> dict:
    """TM1Client.fetch_dimension 的 raw dict → DimensionPayload。

    raw.elements 是 [{"name", "type"}]，canonical 只要 [name]（string list）。
    raw.subsets 是 [{"name", "expression"}]，canonical 只要 [name]。

    注意：subsets 里的 name 可能为 None（旧采集的字符串 `.name` 缺陷），
    这里只保留真实字符串名称，缺失名称绝不伪造为空串混入 canonical。
    """
    elements = [
        e.get("name") for e in (raw.get("elements") or [])
        if isinstance(e, dict) and e.get("name")
    ]
    subsets = [
        s.get("name") for s in (raw.get("subsets") or [])
        if isinstance(s, dict) and isinstance(s.get("name"), str) and s.get("name")
    ]
    return {
        "name": raw.get("name", ""),
        "elements": elements,
        "subsets": subsets,
    }


def _rule_from_cube(cube_payload: dict) -> dict | None:
    """从 Cube 的规则文本派生 RulePayload。

    referenced_cubes 填 []（不在此解析规则语义，留待 Parser/Dependency Engine）。
    无规则文本的 cube 不产出 Rule（避免制造空 Rule）。
    """
    rules = cube_payload.get("rules") or []
    if not rules:
        return None
    return {
        "cube": cube_payload["name"],
        "statement": rules[0] if rules else "",
        "referenced_cubes": [],
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class TM1Collector:
    """TM1 Collector：事实采集 → canonical payload 的薄装配层。

    通过 ``client`` 依赖注入数据源；``tm1`` 是底层连接句柄（真实场景下由
    调用方从 ``TM1Client.connect()`` 获得并传入，mock 场景下可为 None）。
    """

    def __init__(self, client: CollectorClient, tm1: Any = None):
        self.client = client
        self.tm1 = tm1

    def collect_snapshot(self, names: dict[str, list[str]] | None = None,
                         include_system: bool = False) -> dict:
        """采集并返回 canonical Snapshot Payload。

        :param names: 对象名清单（可选）。若为 None，则调用 client.list_all_names()
            获取。传入可避免重复调用 list_all_names 并支持精确控制采集范围。
        :param include_system: 是否收录 ``}`` 开头的系统对象。默认 False，
            被排除的名字放在 payload 的 ``excluded`` 里，不丢事实。
        :return: 符合 Task 8 Schema 的 payload dict（processes/rules/cubes/dimensions）。
        """
        if names is None:
            names = self.client.list_all_names()
        # 采集范围与 exporter 共用同一份规则（ingest.scope）。被排除的名字
        # 作为 excluded 随 payload 返回，导入后可区分「未收录」与「不存在」。
        names, excluded = split_by_scope(names, include_system)

        cubes = []
        rules = []
        for name in names.get("cubes", []):
            raw = self.client.fetch_cube(self.tm1, name)
            cube_payload = _map_cube(raw)
            cubes.append(cube_payload)
            rule = _rule_from_cube(cube_payload)
            if rule is not None:
                rules.append(rule)

        processes = []
        for name in names.get("processes", []):
            raw = self.client.fetch_process(self.tm1, name)
            processes.append(_map_process(raw))

        dimensions = []
        for name in names.get("dimensions", []):
            # 与现有 exporter 一致：} 开头为系统维度，业务维度 is_system=False
            is_system = name.startswith("}")
            raw = self.client.fetch_dimension(self.tm1, name, is_system)
            dimensions.append(_map_dimension(raw))

        payload = {
            "processes": processes,
            "rules": rules,
            "cubes": cubes,
            "dimensions": dimensions,
        }
        if excluded:
            # 采集边界随 payload 走：导入方据此区分「未收录」与「不存在」。
            payload["excluded"] = excluded
        return payload

    def collect_and_validate(self, names: dict[str, list[str]] | None = None,
                             include_system: bool = False) -> dict:
        """采集并校验 canonical payload；校验失败抛 SnapshotSchemaError。"""
        payload = self.collect_snapshot(names, include_system)
        validate_snapshot_payload(payload)
        return payload


def collect_snapshot(client: CollectorClient, tm1: Any = None,
                      names: dict[str, list[str]] | None = None) -> dict:
    """便捷函数：用给定 client 采集一个 canonical Snapshot Payload（见 TM1Collector）。"""
    return TM1Collector(client, tm1).collect_snapshot(names)
