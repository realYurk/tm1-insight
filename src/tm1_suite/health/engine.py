"""TM1 Model Health Engine v1。

基于已经确认的 Model Object Inventory、Reference、Dependency 等**确定性证据**，
发现 TM1 模型中的结构性问题，产出 ``HealthFinding``。

这不是「打分系统」，也不是 AI 判断。核心原则：

```text
Absence of evidence is not evidence of absence.
```

「当前没发现引用」不等于「这个对象一定没有引用」。只有 Collector / Parser /
Resolver 明确能够证明某件事时，Health 才能把它变成 Finding。宁可少报，也不误报。

架构定位：

```text
    Model Object Inventory（Snapshot canonical schema：processes/rules/cubes/dimensions）
        +
    Reference（语法层事实，来自 Parser 产物）
        +
    Dependency（语义层：source depends_on target，Direct）
        ↓
    Health Rules（本模块：确定性、纯函数）
        ↓
    HealthFinding（kind / object / severity / reason / evidence）
```

本模块**不实现**：Health Score / 综合评分 / Health Dashboard / UI / REST API /
CLI / Excel Report / AI / RAG / LLM / Graph DB / NetworkX / Snapshot Compare /
Change Intelligence / Technical Debt Score / 自动修复 / 自动删除 / 业务规则猜测。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from tm1_suite.domain.model import Dependency, HealthFinding, HealthSeverity, Reference

__all__ = [
    "HealthEngine",
    "analyze_health",
    "KIND_BROKEN_REFERENCE",
    "KIND_BROKEN_DEPENDENCY_TARGET",
]


# ---------------------------------------------------------------------------
# Finding kind 常量（确定性标识，用于排序与分类）
# ---------------------------------------------------------------------------

KIND_BROKEN_REFERENCE = "broken_reference"
KIND_BROKEN_DEPENDENCY_TARGET = "broken_dependency_target"


# ---------------------------------------------------------------------------
# 内部：对象 inventory 构建
# ---------------------------------------------------------------------------

def _build_inventory(payload: Mapping) -> set[str]:
    """从 Snapshot payload 构建「当前已知存在的对象名」集合。

    覆盖 canonical schema 的四类对象集合（processes/rules/cubes/dimensions）。
    对象条目兼容 dict（含 ``name`` 或 ``cube``）与 domain 对象（含 ``name``/``cube``
    属性）。缺 name 的条目跳过（不视为对象）。
    """
    names: set[str] = set()
    for key in ("processes", "rules", "cubes", "dimensions"):
        items = payload.get(key) or []
        if not isinstance(items, (list, tuple)):
            continue
        for item in items:
            name = None
            if isinstance(item, dict):
                name = item.get("name") or item.get("cube")
            elif hasattr(item, "name"):
                name = getattr(item, "name")
            elif hasattr(item, "cube"):
                name = getattr(item, "cube")
            if isinstance(name, str) and name:
                names.add(name)
    return names


# ---------------------------------------------------------------------------
# Rule 1：Broken Reference
# ---------------------------------------------------------------------------

def _broken_reference_findings(
    references: Iterable[Reference],
    inventory: set[str],
) -> list[HealthFinding]:
    """Reference 明确指向的对象不存在于 inventory → Broken Reference。

    这是高置信度 Finding：Reference 存在（Parser 明确产出了对某对象的引用），
    而 target 不在当前 Model Object Inventory 中，属于确定事实。
    """
    findings: list[HealthFinding] = []
    for ref in references:
        if ref.target and ref.target not in inventory:
            findings.append(
                HealthFinding(
                    finding=f"引用指向不存在的对象: {ref.target}",
                    severity=HealthSeverity.ERROR,
                    affected_objects=(ref.target,),
                    reason=(
                        f"{ref.source} 引用了 {ref.target}，"
                        f"但该对象不在当前 Model Object Inventory 中"
                    ),
                    evidence={
                        "source": ref.source,
                        "target": ref.target,
                        "reference_kind": ref.kind.value,
                        "operation": ref.operation,
                    },
                    kind=KIND_BROKEN_REFERENCE,
                    object=ref.source,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule 2：Broken Dependency Target
# ---------------------------------------------------------------------------

def _broken_dependency_target_findings(
    dependencies: Iterable[Dependency],
    inventory: set[str],
) -> list[HealthFinding]:
    """Dependency 的 target 不在 inventory → Broken Dependency Target。

    关键前提：Dependency Engine 已过滤「未解析」目标（``<var>`` 形态不产依赖），
    因此能产出的 Dependency 的 target 都是「明确应为模型对象」的字符串。
    若这样的 target 不在 inventory，是确定事实（不是「无法解析」）。

    注意区分：
    - 「无法解析」≠「对象不存在」——无法解析的目标根本不会进入 Dependency；
    - 只有 Dependency 明确产出的 target 缺失，才算 Broken Dependency Target。
    """
    findings: list[HealthFinding] = []
    for dep in dependencies:
        if dep.target and dep.target not in inventory:
            findings.append(
                HealthFinding(
                    finding=f"依赖目标不存在: {dep.target}",
                    severity=HealthSeverity.ERROR,
                    affected_objects=(dep.target,),
                    reason=(
                        f"{dep.source} 依赖 {dep.target}（{dep.kind.value}），"
                        f"但该对象不在当前 Model Object Inventory 中"
                    ),
                    evidence={
                        "source": dep.source,
                        "target": dep.target,
                        "dependency_kind": dep.kind.value,
                        "reference_count": len(dep.references),
                    },
                    kind=KIND_BROKEN_DEPENDENCY_TARGET,
                    object=dep.source,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# 排序 key（确定性）
# ---------------------------------------------------------------------------

def _sort_key(finding: HealthFinding) -> tuple:
    """输出的稳定排序 key：kind → object → target → finding 描述。

    不依赖 dict 插入顺序 / set 顺序 / hash 顺序 / UUID / 时间。
    同一输入（无论正序还是反序）产出完全一致的 Finding 列表。
    """
    target = finding.affected_objects[0] if finding.affected_objects else ""
    return (finding.kind, finding.object, target, finding.finding)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class HealthEngine:
    """Model Health Engine v1（薄封装，纯函数）。

    只做「Inventory + Reference + Dependency → Rules → HealthFinding」，
    不做评分 / UI / 猜测。
    """

    def analyze_health(
        self,
        payload: Mapping,
        references: Iterable[Reference] = (),
        dependencies: Iterable[Dependency] = (),
    ) -> list[HealthFinding]:
        return analyze_health(payload, references, dependencies)


def analyze_health(
    payload: Mapping,
    references: Iterable[Reference] = (),
    dependencies: Iterable[Dependency] = (),
) -> list[HealthFinding]:
    """从当前模型事实分析 Model Health，返回稳定排序的 HealthFinding 列表。

    :param payload: Snapshot payload（canonical schema），提供 Model Object
        Inventory（当前已知存在的对象名集合）。
    :param references: 语法层引用（Parser 产物），用于 Broken Reference 检测。
    :param dependencies: 语义层依赖（Dependency Engine 产物），用于 Broken
        Dependency Target 检测。
    :return: 稳定排序（kind → object → target → finding）的 HealthFinding 列表。
        无证据时返回空列表（不发明问题）。
    """
    inventory = _build_inventory(payload)

    findings: list[HealthFinding] = []
    findings.extend(_broken_reference_findings(references, inventory))
    findings.extend(_broken_dependency_target_findings(dependencies, inventory))
    findings.sort(key=_sort_key)
    return findings
