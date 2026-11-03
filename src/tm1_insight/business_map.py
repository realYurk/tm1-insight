"""业务架构（business-map-1）：用已采集事实回答「这套模型怎么运转」。

只回答三个问题，每一个都能落到具体对象：

1. 数据从哪几类地方来：有 TI 写入的、只靠 Rule 算的、既无写入也无 Rule 的。
2. 最长的一条加工链是什么：Cube → TI → Cube 的跳数与每一步的实现 TI。
3. 哪些 Cube 是枢纽、哪些在调度里。

约束（见 PRODUCT_CONSTITUTION.md「资产提炼优先」）：

- 只用本地索引事实（ti_flows / process_writes_cube / chore_runs_process），不执行 TI、不读业务数据。
- 名称大小写无关；``}`` 开头的系统对象不进入业务版图。
- 链的计算在 DAG 上做最长路；成环的 Cube 单独计数，不假装成链。
- 结果确定性：相同索引产出相同顺序，便于对比与测试。
"""
from __future__ import annotations

import json
from collections import defaultdict, deque

SCHEMA = "business-map-1"

SYSTEM_PREFIX = "}"


def _rows(con, sql: str, params: list | None = None) -> list[tuple]:
    """旧库缺表时返回空结果，不让整页报错。"""
    try:
        return con.execute(sql, params or []).fetchall()
    except Exception:  # noqa: BLE001
        return []


def _canonical_names(con) -> dict[str, str]:
    """lower(name) → 显示名；同一大小写变体优先取原始大小写更完整的那个。"""
    out: dict[str, str] = {}
    for (name,) in _rows(con, "SELECT name FROM cubes ORDER BY name"):
        key = str(name).lower()
        if key not in out:
            out[key] = str(name)
    return out


def _name(name: str, canonical: dict[str, str]) -> str:
    return canonical.get(str(name).lower(), str(name))


def _is_business(name: str) -> bool:
    return not str(name).startswith(SYSTEM_PREFIX)


def build_edges(con) -> list[dict]:
    """Cube → Cube 的流转边：一条边 = 至少一个 TI 从上游读、往下游写。

    ``ti_flows`` 已经做过源码解析；这里只做归一化（大小写、系统对象、自环）。
    端点必须是当前快照里真实存在的 Cube：源码里拼出来的名字（如 ``'a' | pX | 'b'``）
    不是对象，不能画进业务版图。
    """
    canonical = _canonical_names(con)
    grouped: dict[tuple[str, str], dict] = {}
    for process, target, sources in _rows(
        con,
        "SELECT process_name, target_cube, source_cubes FROM ti_flows "
        "WHERE coalesce(target_cube,'') <> '' AND coalesce(source_cubes,'') <> '[]'",
    ):
        target_key = str(target).lower()
        if target_key not in canonical:
            continue
        target_name = canonical[target_key]
        if not _is_business(target_name):
            continue
        try:
            upstream = json.loads(sources) if sources else []
        except Exception:  # noqa: BLE001
            continue
        for source in upstream:
            source_key = str(source).lower()
            if source_key not in canonical:
                continue  # 源码拼串 / 不在本次快照范围的名称，不进入业务版图
            source_name = canonical[source_key]
            if not _is_business(source_name) or source_key == target_key:
                continue  # 系统对象与自引用都不构成流转
            key = (source_key, target_key)
            entry = grouped.setdefault(key, {"source": source_name, "target": target_name,
                                             "processes": set()})
            entry["processes"].add(str(process))
    edges = [
        {"source": e["source"], "target": e["target"], "processes": sorted(e["processes"])}
        for e in grouped.values()
    ]
    edges.sort(key=lambda e: (e["source"].lower(), e["target"].lower()))
    return edges


def _by_source(edges: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        out[edge["source"].lower()].append(edge)
    for key in out:
        out[key].sort(key=lambda e: e["target"].lower())
    return out


def _cycle_members(edges: list[dict]) -> set[str]:
    """真正处在环上的节点（强连通分量 > 1）。

    不能拿「排不进拓扑序」当环：环下游的节点也排不进去，
    把它们算成环会误导迁移顺序。
    """
    adj = _by_source(edges)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    onstack: dict[str, bool] = {}
    stack: list[str] = []
    members: set[str] = set()
    counter = 0
    for root in sorted({e["source"].lower() for e in edges}):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack[root] = True
        work: list[tuple[str, object]] = [(root, iter(adj.get(root, ())))]
        while work:
            node, it = work[-1]
            descended = False
            for edge in it:  # type: ignore[union-attr]
                nxt = edge["target"].lower()
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    onstack[nxt] = True
                    work.append((nxt, iter(adj.get(nxt, ()))))
                    descended = True
                    break
                if onstack.get(nxt):
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    onstack[member] = False
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    members.update(component)
    return members


def _topology(edges: list[dict]) -> tuple[dict[str, int], list[str], int]:
    """DAG 距离（跳数）+ 入度为 0 的起点 + 环上的节点数。

    ``dist`` 只用于决定「从哪些起点找长链」，链本身另行展开。
    """
    nodes: set[str] = set()
    indegree: dict[str, int] = defaultdict(int)
    for edge in edges:
        s, t = edge["source"].lower(), edge["target"].lower()
        nodes.update((s, t))
        indegree[t] += 1
    out = _by_source(edges)
    queue = deque(sorted(n for n in nodes if indegree[n] == 0))
    starts = list(queue)
    remaining = dict(indegree)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for edge in out.get(node, ()):
            nxt = edge["target"].lower()
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    dist: dict[str, int] = {n: 0 for n in nodes}
    for node in order:
        for edge in out.get(node, ()):
            nxt = edge["target"].lower()
            dist[nxt] = max(dist[nxt], dist[node] + 1)
    return dist, starts, len(_cycle_members(edges))


def _walk(edges: list[dict], start: str, max_depth: int = 12, budget: int = 4000) -> list[dict]:
    """从 ``start`` 出发找最长的一条简单路径（带预算，防环、防爆炸）。"""
    out = _by_source(edges)
    best: list[dict] = []
    stack: list[tuple[str, tuple[str, ...], list[dict]]] = [(start, (start,), [])]
    steps = 0
    while stack:
        node, visited, hops = stack.pop()
        if len(hops) > len(best):
            best = hops
        if len(hops) >= max_depth:
            continue
        for edge in reversed(out.get(node, ())):
            nxt = edge["target"].lower()
            if nxt in visited:
                continue  # 环：跳过，不重复进入
            steps += 1
            if steps > budget:
                return best
            stack.append((nxt, visited + (nxt,), hops + [edge]))
    return best


def _to_chain(hops: list[dict]) -> dict:
    """把边走成链；hops 只暴露 from / to / 实现 TI，页面不需要知道内部键名。"""
    if not hops:
        return {"length": 0, "path": [], "hops": []}
    steps = [{"from": h["source"], "to": h["target"], "processes": h["processes"]} for h in hops]
    return {
        "length": len(steps),
        "path": [steps[0]["from"]] + [s["to"] for s in steps],
        "hops": steps,
    }


def longest_chain(edges: list[dict]) -> dict:
    """模型里最长的一条加工链。没有边时返回长度 0。"""
    if not edges:
        return {"length": 0, "path": [], "hops": [], "cyclic": 0}
    dist, starts, cyclic = _topology(edges)
    candidates = starts or sorted(dist, key=lambda n: (-dist[n], n))
    best = {"length": 0, "path": [], "hops": []}
    for start in candidates[:40]:
        chain = _to_chain(_walk(edges, start))
        if chain["length"] > best["length"]:
            best = chain
    best["cyclic"] = cyclic
    return best


def top_chains(edges: list[dict], limit: int = 4) -> list[dict]:
    """几条不同的长链：从不同起点长出，按跳数排序。

    只用于横向看「业务是怎么串起来的」，不是完整枚举。
    """
    if not edges:
        return []
    dist, starts, _ = _topology(edges)
    candidates = starts or sorted(dist, key=lambda n: (-dist[n], n))
    candidates = sorted(candidates, key=lambda n: (-dist[n], n))[:60]
    chains: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    used_starts: set[str] = set()
    for start in candidates:
        if start in used_starts:
            continue
        chain = _to_chain(_walk(edges, start, max_depth=12, budget=3000))
        if chain["length"] < 2:
            continue
        signature = tuple(p.lower() for p in chain["path"])
        if signature in seen:
            continue
        seen.add(signature)
        used_starts.add(start)  # 同一个起点只保留最长的一条
        chains.append(chain)
        if len(chains) >= max(1, limit):
            break
    chains.sort(key=lambda c: (-c["length"], [p.lower() for p in c["path"]]))
    return chains


def hubs(edges: list[dict], limit: int = 6) -> list[dict]:
    """枢纽 Cube：直接下游最多（被最多流程消费）的对象。"""
    downstream: dict[str, set[str]] = defaultdict(set)
    upstream: dict[str, set[str]] = defaultdict(set)
    display: dict[str, str] = {}
    for edge in edges:
        s, t = edge["source"].lower(), edge["target"].lower()
        downstream[s].add(t)
        upstream[t].add(s)
        display[s] = edge["source"]
        display[t] = edge["target"]
    rows = [
        {"name": display[key], "downstream": len(downstream[key]),
         "upstream": len(upstream.get(key, ()))}
        for key in downstream
    ]
    rows.sort(key=lambda r: (-r["downstream"], -r["upstream"], r["name"].lower()))
    return rows[: max(1, limit)]


def ends(edges: list[dict]) -> dict:
    """链的两端：没有任何上游的起点、没有任何下游的终点。"""
    sources, targets = set(), set()
    for edge in edges:
        sources.add(edge["source"].lower())
        targets.add(edge["target"].lower())
    return {"starts": len(sources - targets), "ends": len(targets - sources)}


def overview(con) -> dict:
    """业务架构页的全部事实。任何一段取不到都不影响其它段落。"""
    totals = {
        "cubes": int((_rows(con, "SELECT count(*) FROM cubes WHERE name NOT LIKE '}%'") or [[0]])[0][0] or 0),
        "writers": int((_rows(con, "SELECT count(DISTINCT cube_name) FROM process_writes_cube "
                                     "WHERE cube_name NOT LIKE '}%'") or [[0]])[0][0] or 0),
        "processes": int((_rows(con, "SELECT count(*) FROM processes WHERE name NOT LIKE '}%'") or [[0]])[0][0] or 0),
        "chores": int((_rows(con, "SELECT count(*) FROM chores") or [[0]])[0][0] or 0),
        "scheduled_processes": int((_rows(con, "SELECT count(DISTINCT process_name) FROM chore_runs_process")
                                    or [[0]])[0][0] or 0),
    }

    rule_only = int((_rows(con, """
        SELECT count(*) FROM cubes c
        WHERE c.name NOT LIKE '}%' AND coalesce(c.rules,'') <> ''
          AND lower(c.name) NOT IN (SELECT lower(cube_name) FROM process_writes_cube)
    """) or [[0]])[0][0] or 0)
    no_source = int((_rows(con, """
        SELECT count(*) FROM cubes c
        WHERE c.name NOT LIKE '}%' AND coalesce(c.rules,'') = ''
          AND lower(c.name) NOT IN (SELECT lower(cube_name) FROM process_writes_cube)
    """) or [[0]])[0][0] or 0)

    edges = build_edges(con)
    chain = longest_chain(edges)
    chains = top_chains(edges)
    hero_path = [p.lower() for p in chain["path"]]
    chains = [c for c in chains if [p.lower() for p in c["path"]] != hero_path]
    # Chore 步骤通常只是壳：真正写数的 TI 要通过调用链才看得到，故取两层闭包。
    scheduled_cubes = int((_rows(con, """
        WITH lvl1 AS (SELECT lower(process_name) AS p FROM chore_runs_process),
        lvl2 AS (SELECT lower(callee) AS p FROM ti_business_calls
                 WHERE lower(caller) IN (SELECT p FROM lvl1)),
        lvl3 AS (SELECT lower(callee) AS p FROM ti_business_calls
                 WHERE lower(caller) IN (SELECT p FROM lvl2)),
        sched AS (SELECT p FROM lvl1 UNION SELECT p FROM lvl2 UNION SELECT p FROM lvl3)
        SELECT count(DISTINCT w.cube_name) FROM process_writes_cube w
        WHERE lower(w.process_name) IN (SELECT p FROM sched) AND w.cube_name NOT LIKE '}%'
    """) or [[0]])[0][0] or 0)

    return {
        "schema": SCHEMA,
        "totals": totals,
        "rule_only": rule_only,
        "no_source": no_source,
        "edges": len(edges),
        "chain": chain,
        "chains": chains,
        "hubs": hubs(edges),
        "ends": ends(edges),
        "scheduled_cubes": scheduled_cubes,
    }


def headline(data: dict) -> str:
    """一句话结论：模型里有多少数据是被 TI 写出来的，多少是 Rule 算出来的。"""
    totals = data.get("totals", {})
    cubes = totals.get("cubes", 0)
    if not cubes:
        return "当前数据源没有可用的 Cube 事实。"
    return (f"{cubes} 个业务 Cube 中，{totals.get('writers', 0)} 个由 TI 写入，"
            f"{data.get('rule_only', 0)} 个只靠 Rule，"
            f"{data.get('no_source', 0)} 个既无写入也无 Rule。")


def empty() -> dict:
    """取不到事实时的空结构：页面仍然可用，只是说明没有数据。"""
    return {
        "schema": SCHEMA,
        "totals": {"cubes": 0, "writers": 0, "processes": 0, "chores": 0, "scheduled_processes": 0},
        "rule_only": 0, "no_source": 0, "edges": 0,
        "chain": {"length": 0, "path": [], "hops": [], "cyclic": 0},
        "chains": [], "hubs": [], "ends": {"starts": 0, "ends": 0},
        "scheduled_cubes": 0,
    }
