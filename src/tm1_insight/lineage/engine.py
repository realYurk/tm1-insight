"""TM1 Lineage Engine v1。

基于 Dependency Engine 产出的 **Direct Dependency**，计算**传递闭包**，
回答「一个对象的上游 / 下游有哪些」以及「为什么存在这条 Lineage」。

架构定位：

```text
    Reference（语法层事实）
        ↓ 语义解释
    Dependency（语义层：source depends_on target，Direct）
        ↓ 传递闭包（本模块）
    Lineage（source → target 的传递可达关系，含 path / depth）
```

边界约束（对齐 Task 11 已锁定的契约）：

- **Dependency = Direct**，Lineage = **Transitive**。本模块不做 Parser / Resolver /
  Dependency，只消费 Dependency 集合做图遍历。
- **不重新解析 TI**：输入是 ``Sequence[Dependency]``，绝不读取 TI 源码。
- **不做业务猜测式 Lineage**：没有 Direct Dependency 就没有 Lineage（不因
  「同名 cube / 同维度 / 名称相似」而强加关系）。
- **Cycle 安全**：DFS/BFS 用 visited 防环，绝不无限循环 / 爆栈。
- **纯函数 + 确定性**：不依赖 DuckDB / NetworkX / Neo4j / 图数据库，相同输入
  （无论顺序）产出相同、稳定排序的 Lineage。

本模块**不实现** Impact Analysis / Model Health / Snapshot Compare /
Change Intelligence / Graph DB / AI。
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Sequence

from tm1_insight.domain.model import Dependency, Lineage

__all__ = [
    "build_lineage",
    "get_downstream",
    "get_upstream",
    "build_adjacency",
    "LineageEngine",
]


# ---------------------------------------------------------------------------
# 内部：邻接表构建 + BFS 传递闭包
# ---------------------------------------------------------------------------

def build_adjacency(
    dependencies: Iterable[Dependency],
) -> dict[str, list[tuple[str, Dependency]]]:
    """把 Dependency 集合构建为邻接表：source → [(target, dependency), ...]。

    公开此函数供批量调用方（如 Change Intelligence）复用同一份邻接表，
    避免对每个对象重复建图（O(N×E) 性能问题）。
    """
    return _build_adjacency(dependencies)

def _build_adjacency(
    dependencies: Iterable[Dependency],
) -> dict[str, list[tuple[str, Dependency]]]:
    """把 Dependency 集合构建为邻接表：source → [(target, dependency), ...]。

    同一 (source, target) 可能有多条 Dependency（不同 kind），全部保留，
    供 path 选择时取「字典序最小 path」的确定性规则。
    """
    adj: dict[str, list[tuple[str, Dependency]]] = defaultdict(list)
    for dep in dependencies:
        adj[dep.source].append((dep.target, dep))
    # 稳定化：每个 source 的出边按 (target, kind.value) 排序，保证遍历确定。
    for src in adj:
        adj[src].sort(key=lambda t: (t[0], t[1].kind.value))
    return adj


def _shortest_paths(adj: dict[str, list[tuple[str, Dependency]]], start: str,
                    max_depth: int | None = None, max_nodes: int | None = None) -> list[Lineage]:
    """从 ``start`` 出发做 BFS，返回所有可达 target 的 Lineage（含 direct 自身）。

    每个 (source, target) 只保留一条 Lineage：BFS 天然给出最短跳数；同一深度
    多路径时，邻接表已按 (target, kind) 稳定排序，故取到的是字典序最小的路径，
    保证确定性。

    Cycle 安全：BFS 用「当前路径内去重」（``nxt in path`` 即跳过）防环。
    自环 A→A 只作为 depth=1 的 direct 边产出一次，不会反复入队导致无限循环。

    纯函数：不共享任何模块级可变状态，结果只依赖入参。
    """
    # 以 (source, target) 为 key 去重，保留首见（BFS 最短）路径
    seen: dict[tuple[str, str], Lineage] = {}

    # queue 元素：当前节点、到当前节点的完整路径（节点名序列）、支撑路径的直接依赖列表
    queue: deque[tuple[str, tuple[str, ...], tuple[Dependency, ...]]] = deque()
    queue.append((start, (start,), ()))

    while queue:
        node, path, deps = queue.popleft()
        if max_depth is not None and len(deps) >= max_depth:
            continue
        for nxt, dep in adj.get(node, []):
            if nxt == node and nxt == start:
                # 自环（start→start）：作为 depth=1 的 direct self 边产出一次，
                # 且不继续扩展（扩展会回到 start 造成无限循环）。
                key = (start, nxt)
                if key not in seen:
                    seen[key] = Lineage(
                        target=nxt,
                        dependencies=(dep,),
                        source=start,
                        path=(start, nxt),
                        depth=1,
                    )
                continue
            if nxt in path:
                # 环：nxt 已在此路径中，跳过（不重复入队，防无限循环）
                continue
            key = (start, nxt)
            if key in seen:
                # BFS visits shortest paths first. Sorted adjacency also makes
                # the first equal-length path deterministic. Expanding this node
                # again enumerates exponentially many paths in converging DAGs.
                continue
            if max_nodes is not None and len(seen) >= max_nodes:
                continue
            new_path = path + (nxt,)
            new_deps = deps + (dep,)
            depth = len(new_path) - 1
            lin = Lineage(
                target=nxt,
                dependencies=new_deps,
                source=start,
                path=new_path,
                depth=depth,
            )
            seen[key] = lin
            queue.append((nxt, new_path, new_deps))

    return list(seen.values())


def build_lineage(dependencies: Iterable[Dependency]) -> list[Lineage]:
    """从 Dependency 集合构建传递闭包，返回稳定排序的 Lineage 列表。

    结果包含：
    - direct 边（depth=1）：``A → B``（Dependency 本身也作为 Lineage 表达）。
    - transitive 边（depth≥2）：``A → C``（由 ``A→B``、``B→C`` 推导）。

    每条 Lineage 携带 ``path``（完整路径）与 ``depth``（跳数），可解释来源。

    确定性：相同 Dependency 集合（无论输入顺序）产出相同、稳定排序的结果。
    排序 key：``(source, target, depth)``。
    """
    adj = _build_adjacency(dependencies)
    all_lin: dict[tuple[str, str], Lineage] = {}
    for start in sorted(adj.keys()):
        for lin in _shortest_paths(adj, start):
            all_lin[(lin.source, lin.target)] = lin
    result = list(all_lin.values())
    result.sort(key=lambda l: (l.source, l.target, l.depth or 0))
    return result


def get_downstream(dependencies: Iterable[Dependency], source: str, _adj: dict | None = None,
                   *, max_depth: int | None = None, max_nodes: int | None = None) -> list[Lineage]:
    """返回 ``source`` 的所有下游可达关系（按 depth 升序、target 字典序稳定）。

    ``_adj`` 为可选预构建邻接表（性能优化：批量调用时复用，避免重复建图）。
    """
    adj = _adj if _adj is not None else _build_adjacency(dependencies)
    if source not in adj:
        return []
    lins = _shortest_paths(adj, source, max_depth=max_depth, max_nodes=max_nodes)
    lins.sort(key=lambda l: (l.depth or 0, l.target))
    return lins


def get_upstream(dependencies: Iterable[Dependency], target: str, _adj: dict | None = None) -> list[Lineage]:
    """返回所有能到达 ``target`` 的上游关系（反转图后做下游可达）。

    返回的 Lineage 保持「source → target」方向（source 是上游起点，target 是终点）。

    ``_adj`` 为可选预构建邻接表（性能优化：批量调用时复用，避免重复建图）。
    """
    adj = _adj if _adj is not None else _build_adjacency(dependencies)
    # 反转图：上游 = 反转图中的下游
    rev: dict[str, list[tuple[str, Dependency]]] = defaultdict(list)
    for src, edges in adj.items():
        for tgt, dep in edges:
            rev[tgt].append((src, dep))
    for t in rev:
        rev[t].sort(key=lambda x: (x[0], x[1].kind.value))
    if target not in rev:
        return []
    lins = _shortest_paths(rev, target)
    # 反转图中 path 是 target → ... → upstream，需翻回 upstream → ... → target。
    # 反转图里 Lineage 的 source=target（真实终点）、target=上游节点（真实起点）。
    out: list[Lineage] = []
    for lin in lins:
        out.append(Lineage(
            target=target,                 # 真实终点 = 传入的 target
            dependencies=lin.dependencies,
            source=lin.target,             # 真实起点 = 反转图里的终点（上游节点）
            path=tuple(reversed(lin.path)),
            depth=lin.depth,
        ))
    out.sort(key=lambda l: (l.source, l.depth or 0))
    return out


class LineageEngine:
    """Lineage Engine v1（薄封装，纯函数）。

    只做「Dependency → 图遍历 → Lineage」，不新增 Parser/Dependency 能力。
    """

    def build_lineage(self, dependencies: Iterable[Dependency]) -> list[Lineage]:
        return build_lineage(dependencies)

    def get_downstream(self, dependencies: Iterable[Dependency], source: str) -> list[Lineage]:
        return get_downstream(dependencies, source)

    def get_upstream(self, dependencies: Iterable[Dependency], target: str) -> list[Lineage]:
        return get_upstream(dependencies, target)
