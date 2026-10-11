"""TM1 Impact Analysis Engine v1。

给定一个发生变化的 ``source``，计算「沿已确认的依赖关系，哪些对象会受影响」，
并明确影响是 ``direct`` 还是 ``indirect``，同时保留传播路径与 depth，保证结果
可解释、可测试、可复现。

架构定位：

```text
    Reference（语法层事实）
        ↓ 语义解释
    Dependency（语义层：source depends_on target，Direct）
        ↓ 传递闭包（lineage）
    Lineage（source → target 的传递可达关系，含 path / depth）
        ↓ 复用 get_downstream（本模块）
    Impact（从指定 source 出发的 downstream 影响范围）
```

第一原则（对齐 AI_INSTRUCTIONS §6.2 / §16）：

- **Impact 是基于 Dependency / Lineage 的确定性分析，不进行业务猜测。**
- 本模块**不重新计算图**：直接复用 ``lineage.get_downstream``，把 Lineage
  提升为 Impact 语义，保证 Dependency / Lineage / Impact 三者职责统一。
- **不重新解析 TI**：输入是 ``Sequence[Dependency]``，绝不读取 TI 源码。
- **不重新实现 Parser / Resolver / BFS**。
- **纯函数 + 确定性**：不依赖 DuckDB / NetworkX / Neo4j / 图数据库 / AI，
  相同输入（无论顺序）产出相同、稳定排序的 Impact。

本模块**只实现 downstream impact**（给定 source → 哪些对象受影响）。
**不实现** upstream impact（"某个 Cube 的上游对象是什么"），那是未来任务。

本模块**不实现**：Model Health / Technical Debt / Snapshot Compare /
Change Intelligence / Impact Report / Excel Export / Web UI / CLI / REST API /
Graph DB / AI。
"""
from __future__ import annotations

from typing import Iterable, Sequence

from tm1_suite.domain.model import Dependency, Impact, ImpactKind, Lineage
from tm1_suite.lineage import get_downstream

__all__ = [
    "ImpactEngine",
    "analyze_impact",
    "get_impact",
]


# ---------------------------------------------------------------------------
# Lineage → Impact 提升
# ---------------------------------------------------------------------------

def _kind_from_depth(depth: int | None) -> ImpactKind:
    """由 depth 确定性推导 Impact 分类。

    direct 当且仅当 depth == 1；否则 indirect。depth 为 None（未计算）
    保守归为 indirect（不应把未证明的直接关系误判为 direct）。
    """
    if depth == 1:
        return ImpactKind.DIRECT
    return ImpactKind.INDIRECT


def _impact_from_lineage(lin: Lineage, source: str) -> Impact:
    """把一条 Lineage 提升为 Impact，保留 path / depth / dependencies 可解释性。"""
    return Impact(
        source=source,
        target=lin.target,
        kind=_kind_from_depth(lin.depth),
        depth=lin.depth,
        path=tuple(lin.path),
        dependencies=tuple(lin.dependencies),
    )


# ---------------------------------------------------------------------------
# 排序 key（确定性）
# ---------------------------------------------------------------------------

def _sort_key(impact: Impact) -> tuple:
    """输出的稳定排序 key：depth 升序 → target 字典序。

    不依赖 dict 插入顺序 / set 顺序 / hash 顺序 / UUID / 时间。
    同一输入（无论依赖正序还是反序）产出完全一致的 Impact 结果。
    """
    return (impact.depth if impact.depth is not None else 0, impact.target)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ImpactEngine:
    """Impact Analysis Engine v1（薄封装，纯函数）。

    只做「Dependency → Lineage → Impact」，不新增 Parser/Dependency/Lineage 能力。
    """

    def analyze_impact(
        self,
        dependencies: Iterable[Dependency],
        source: str,
    ) -> list[Impact]:
        """分析 ``source`` 发生变化时的 downstream impact，返回稳定排序的 Impact 列表。"""
        return analyze_impact(dependencies, source)


def analyze_impact(
    dependencies: Iterable[Dependency],
    source: str,
) -> list[Impact]:
    """从 Dependency 集合分析 ``source`` 的 downstream impact。

    直接复用 Lineage 的 ``get_downstream``（BFS 传递闭包），把每条 Lineage
    提升为 Impact。lineage 已保证：
    - direct（depth=1）与 transitive（depth>=2）正确区分；
    - path / depth / dependencies 完整保留（可解释）；
    - cycle 安全（不无限循环 / 爆栈 / 重复 target）；
    - 多路径只保留一条 deterministic path（字典序最小）；
    - 确定性（与输入顺序无关）。

    :param dependencies: 直接依赖集合（source depends_on target）。
    :param source: 分析起点对象名。
    :return: 稳定排序（depth 升序 → target 字典序）的 Impact 列表。
        若 source 无任何下游，返回空列表（不发明影响）。
    """
    lineages: Sequence[Lineage] = get_downstream(dependencies, source)
    impacts = [_impact_from_lineage(lin, source) for lin in lineages]
    impacts.sort(key=_sort_key)
    return impacts


def get_impact(
    dependencies: Iterable[Dependency],
    source: str,
) -> list[Impact]:
    """便捷函数：等价于 ``analyze_impact``。"""
    return analyze_impact(dependencies, source)
