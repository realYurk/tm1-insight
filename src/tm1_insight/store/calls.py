"""进程调用事实的唯一生产者。

为什么需要这一层：采集阶段把调用写进了三张表，各自口径不同——

- ``process_calls_process``：正则扫源码得到的**字面**调用目标，含 ``}`` 框架进程，
  不含变量目标；
- ``ti_business_calls``：语句级解析器**解析变量后**的目标，因此能补上正则漏掉的
  ``ExecuteProcess(sProc)``（变量已赋值的情况），但条件不可解析时会把
  ``<sProc2>``、``<DimNm(...)>`` 这类**动态占位**当成名字写进来；
- ``ti_framework_calls``：``}bedrock.*`` / ``}APQ.*`` 及其用途。

三张表各被不同页面直接读取，于是同一个 TI 在页头写「被 3 个进程调用」，
在调用树里只显示 2 个——同一页面自相矛盾（本机 Demo 数据上 113 个 TI 不一致）。

本模块把三者合成一个事实源，并显式区分四类目标：

============  ================================================  ==================
kind          含义                                              能否当作进程节点
============  ================================================  ==================
``literal``   源码字面目标，且目录中存在同名 TI               是（已确认）
``framework`` ``}`` 前缀框架进程                                是，但标注为框架
``missing``   源码字面目标，目录中没有同名 TI                 显示，但不做链接
``dynamic``   目标是变量/表达式，未能解析成固定成员            否，只报「有几处未解析」
============  ================================================  ==================

``dynamic`` 尤其重要：``<sProc2>`` 不是进程名，把它的字符串渲染成可点击的
进程链接，就是把动态坐标当成固定成员——产品事实规则明确禁止。

所有「谁调用我 / 我调用谁」的结论（TI 页页头、调用树、学习报告、导出）
都必须经过本模块，页面只做投影。
"""
from __future__ import annotations

import duckdb

KIND_LITERAL = "literal"
KIND_FRAMEWORK = "framework"
KIND_MISSING = "missing"
KIND_DYNAMIC = "dynamic"

KINDS = (KIND_LITERAL, KIND_FRAMEWORK, KIND_MISSING, KIND_DYNAMIC)

#: 展示用中文标签。集中在这里，避免各页面各写一套措辞。
KIND_LABEL = {
    KIND_LITERAL: "字面调用",
    KIND_FRAMEWORK: "框架调用",
    KIND_MISSING: "目录中无此 TI",
    KIND_DYNAMIC: "动态目标，未解析",
}

#: 可以当成「进程」展示的 kind（dynamic 不行）。
NODE_KINDS = (KIND_LITERAL, KIND_FRAMEWORK, KIND_MISSING)

#: (表名, 全量读取, 单个 TI 的读取 —— 后者把过滤下推到表扫描，避免先合并全模型)
_SOURCES = (
    ("ti_business_calls",
     "SELECT caller, callee, params AS detail FROM ti_business_calls",
     "SELECT caller, callee, params AS detail FROM ti_business_calls WHERE caller = ? OR callee = ?"),
    ("process_calls_process",
     "SELECT caller, callee, NULL AS detail FROM process_calls_process",
     "SELECT caller, callee, NULL AS detail FROM process_calls_process WHERE caller = ? OR callee = ?"),
    ("ti_framework_calls",
     "SELECT process_name, callee, purpose AS detail FROM ti_framework_calls",
     "SELECT process_name, callee, purpose AS detail FROM ti_framework_calls WHERE process_name = ? OR callee = ?"),
)


def is_dynamic_target(name: str | None) -> bool:
    """``<sProc2>`` / ``<DimNm(...)>`` / ``<GetProcessName(...)>.Localized`` 这类占位不是固定成员。

    判据是「以 ``<`` 开头」而不是「形如 ``<...>``」：解析器对拼接出来的目标会保留
    后缀（例如 ``.Localized``），只看首字符才不会漏。
    """
    return bool(name) and name.startswith("<")


def available_sources(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """旧快照可能缺表；缺表时如实少读一份，而不是整体失败。"""
    present = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    return tuple(name for name, *_ in _SOURCES if name in present)


def _classify_cte(union: str, name: str) -> str:
    """把「三张表合并 + 分类」的规则写成一份 SQL，供全量与单对象两条路径共用。"""
    return f"""
    WITH raw AS (
        {union}
    ), merged AS (
        SELECT caller, callee, max(detail) AS detail
        FROM raw WHERE caller IS NOT NULL AND callee IS NOT NULL AND callee <> ''
        GROUP BY caller, callee
    ), {name} AS (
        SELECT merged.caller, merged.callee, merged.detail,
               CASE
                   WHEN merged.callee LIKE '<%' THEN '{KIND_DYNAMIC}'
                   WHEN merged.callee LIKE '}}%' THEN '{KIND_FRAMEWORK}'
                   WHEN known.name IS NULL THEN '{KIND_MISSING}'
                   ELSE '{KIND_LITERAL}'
               END AS kind
        FROM merged
        -- processes.name 是主键，直接连接不会放大行数；用子查询 + DISTINCT 会多花约 13 ms。
        LEFT JOIN processes AS known ON known.name = merged.callee
    )
    """


def edges_cte(con: duckdb.DuckDBPyConnection, name: str = "call_edge") -> str:
    """生成 ``WITH <name> AS (...)`` 片段，供本模块与调用树共用同一份口径。

    结果列：``caller`` / ``callee`` / ``kind`` / ``detail``。
    同一 (caller, callee) 在两张表都出现时只保留一行，``detail`` 取非空的一侧。
    """
    present = available_sources(con)
    parts = [sql for table, sql, _ in _SOURCES if table in present]
    if not parts:
        # 没有任何来源表：给一个空集合，调用方仍能正常工作。
        return (
            f"WITH {name} AS (SELECT CAST(NULL AS VARCHAR) AS caller, CAST(NULL AS VARCHAR) AS callee,"
            " CAST(NULL AS VARCHAR) AS detail, CAST(NULL AS VARCHAR) AS kind WHERE FALSE)"
        )
    return _classify_cte(" UNION ALL ".join(parts), name)


def object_edges_cte(con: duckdb.DuckDBPyConnection, process: str, alias: str = "call_edge") -> tuple[str, list[str]]:
    """单个 TI 的上下游边（过滤下推到表扫描，不先合并全模型），返回 ``(CTE 文本, 参数量)``。

    每个来源表贡献两个占位符（左侧 caller / 右侧 callee），因此调用方传入的
    参数就是 ``[process, process] × 来源表数量``。
    """
    present = available_sources(con)
    parts = [filtered for table, _, filtered in _SOURCES if table in present]
    if not parts:
        return (
            f"WITH {alias} AS (SELECT CAST(NULL AS VARCHAR) AS caller, CAST(NULL AS VARCHAR) AS callee,"
            " CAST(NULL AS VARCHAR) AS detail, CAST(NULL AS VARCHAR) AS kind WHERE FALSE)",
            [],
        )
    return _classify_cte(" UNION ALL ".join(parts), alias), [process, process] * len(parts)


def edges(
    con: duckdb.DuckDBPyConnection,
    *,
    caller: str | None = None,
    callee: str | None = None,
    kinds: tuple[str, ...] | None = None,
    cte: str | None = None,
) -> list[dict]:
    """按方向取调用边。``caller`` 给定时返回该 TI 调用了谁，``callee`` 给定时返回谁调用它。

    ``cte`` 可由调用方传入已生成的片段，避免一次请求里反复探测有哪些来源表。
    """
    where, params = [], []
    if caller is not None:
        where.append("caller = ?")
        params.append(caller)
    if callee is not None:
        where.append("callee = ?")
        params.append(callee)
    if kinds is not None:
        where.append("kind IN (" + ",".join("?" for _ in kinds) + ")")
        params.extend(kinds)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = con.execute(
        (cte or edges_cte(con))
        + f" SELECT DISTINCT caller, callee, kind, detail FROM call_edge{clause} ORDER BY callee, caller",
        params,
    ).fetchall()
    return [{"caller": r[0], "callee": r[1], "kind": r[2], "detail": r[3]} for r in rows]


def summary(con: duckdb.DuckDBPyConnection, name: str) -> dict:
    """一个 TI 的调用事实摘要：谁调用它（已确认集合）+ 它调用谁（按 kind 分类）。

    ``callers`` 是**去重后的调用方进程名**。调用方本身必定是目录里的 TI
    （采集只记录真实进程名），因此这里不需要再分 kind。

    ``dynamic_callees`` 是「有几处调用目标没能解析成固定成员」——一个计数，
    不是进程名列表；这些目标可能是任何 TI，不能点名。
    """
    if is_dynamic_target(name):
        # 占位名不是成员：不存在「谁调用 <sProc2>」这种事实，直接返回空集。
        return {"callers": [], "callees": [], "counts": {"callers": 0, "callees": {k: 0 for k in KINDS}},
                "dynamic_callees": 0, "node_callees": []}
    # 过滤下推到三张表，只算这个 TI 的上下游；一条 SQL 同时拿到两个方向。
    cte, params = object_edges_cte(con, name)
    rows = con.execute(
        cte + " SELECT DISTINCT caller, callee, kind, detail FROM call_edge ORDER BY callee, caller",
        params,
    ).fetchall()
    inbound = [r for r in rows if r[1] == name]
    outbound = [r for r in rows if r[0] == name]
    callers = sorted({r[0] for r in inbound})
    counts = {kind: 0 for kind in KINDS}
    for row in outbound:
        counts[row[2]] = counts.get(row[2], 0) + 1
    callees = [
        {"caller": r[0], "callee": r[1], "kind": r[2], "detail": r[3]}
        for r in sorted(outbound, key=lambda r: (KINDS.index(r[2]) if r[2] in KINDS else 99, r[1]))
    ]
    return {
        "callers": callers,
        "callees": callees,
        "counts": {"callers": len(callers), "callees": counts},
        "dynamic_callees": counts.get(KIND_DYNAMIC, 0),
        "node_callees": [e for e in callees if e["kind"] in NODE_KINDS],
    }
