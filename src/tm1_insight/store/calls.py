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

#: 对象范围。这不是「过滤掉不重要的事实」，而是把两类对象分开看：
#: ``}`` 开头是 TM1 自带/框架对象（}bedrock.*、}APQ.*、}DimensionAttributes …），
#: 它们由产品方维护，改不了也不该改；业务 TI 才是使用者自己写的那部分。
#: 实测（本机 Demo，3 437 个进程）：1365 个业务 TI 的下游里平均 82% 是系统对象，
#: 不分开，调用树基本就是一片 }bedrock.*，看不见自己调用的业务子进程。
SCOPE_BUSINESS = "business"
SCOPE_SYSTEM = "system"
SCOPE_ALL = "all"
SCOPES = (SCOPE_BUSINESS, SCOPE_SYSTEM, SCOPE_ALL)
SCOPE_LABEL = {SCOPE_BUSINESS: "业务对象", SCOPE_SYSTEM: "系统对象", SCOPE_ALL: "全部"}

SYSTEM_PREFIX = "}"

#: 证据来源（哪张表产出这条边）。与 kind 是两个正交维度：
#: kind 说「这条边指向什么」，source 说「这条边凭什么被记录下来」。
#: 页面上的「为什么数字变了」只能靠 source 解释——131 与 1996 的差别就在这一层。
SRC_REGEX = "regex"          # process_calls_process：正则扫源码，只认字面写死的进程名
SRC_RESOLVED = "resolved"    # ti_business_calls：语句级解析，变量已赋值才能得出目标
SRC_FRAMEWORK = "framework"  # ti_framework_calls：框架进程调用表

SOURCES = (SRC_REGEX, SRC_RESOLVED, SRC_FRAMEWORK)

SOURCE_LABEL = {
    SRC_REGEX: "正则扫源码",
    SRC_RESOLVED: "变量解析",
    SRC_FRAMEWORK: "框架调用表",
}

#: 主证据优先级：字面写死最硬，框架表次之，变量解析最弱（依赖赋值可解析）。
#: 同一对 (caller, callee) 可能被多张表记录，页面只显示主证据，其余在计数里体现。
_SOURCE_RANK = (SRC_REGEX, SRC_FRAMEWORK, SRC_RESOLVED)

#: (表名, 全量读取, 单个 TI 的读取 —— 后者把过滤下推到表扫描，避免先合并全模型)
_SOURCES = (
    ("ti_business_calls",
     f"SELECT caller, callee, params AS detail, '{SRC_RESOLVED}' AS src FROM ti_business_calls",
     f"SELECT caller, callee, params AS detail, '{SRC_RESOLVED}' AS src FROM ti_business_calls"
     " WHERE caller = ? OR callee = ?"),
    ("process_calls_process",
     f"SELECT caller, callee, NULL AS detail, '{SRC_REGEX}' AS src FROM process_calls_process",
     f"SELECT caller, callee, NULL AS detail, '{SRC_REGEX}' AS src FROM process_calls_process"
     " WHERE caller = ? OR callee = ?"),
    ("ti_framework_calls",
     f"SELECT process_name, callee, purpose AS detail, '{SRC_FRAMEWORK}' AS src FROM ti_framework_calls",
     f"SELECT process_name, callee, purpose AS detail, '{SRC_FRAMEWORK}' AS src FROM ti_framework_calls"
     " WHERE process_name = ? OR callee = ?"),
)


def is_dynamic_target(name: str | None) -> bool:
    """``<sProc2>`` / ``<DimNm(...)>`` / ``<GetProcessName(...)>.Localized`` 这类占位不是固定成员。

    判据是「以 ``<`` 开头」而不是「形如 ``<...>``」：解析器对拼接出来的目标会保留
    后缀（例如 ``.Localized``），只看首字符才不会漏。
    """
    return bool(name) and name.startswith("<")


def is_system_object(name: str | None) -> bool:
    """``}`` 开头是 TM1 自带对象；其余是使用者自己写的业务对象。

    只用前缀判断，不猜语义：``}bedrock.*`` 是框架，``}DimensionAttributes`` 是控制立方体，
    ``}ElementAttributes_XXX`` 是属性视图——但它们在「这不关我的事」这一点上相同。
    """
    return bool(name) and name.startswith(SYSTEM_PREFIX)


def scope_of(name: str | None) -> str:
    """给对象分范围。占位单独一类，因为它既不是业务对象也不是系统对象。"""
    if is_dynamic_target(name):
        return KIND_DYNAMIC
    return SCOPE_SYSTEM if is_system_object(name) else SCOPE_BUSINESS


def in_scope(name: str | None, scope: str) -> bool:
    """``scope`` 只接受三种值；``all`` 放行一切（占位目标由调用方另行处理）。"""
    if scope == SCOPE_ALL:
        return True
    return scope_of(name) == scope


def available_sources(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """旧快照可能缺表；缺表时如实少读一份，而不是整体失败。"""
    present = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    return tuple(name for name, *_ in _SOURCES if name in present)


def _classify_cte(union: str, name: str) -> str:
    """把「三张表合并 + 分类 + 记录来源」的规则写成一份 SQL，供全量与单对象两条路径共用。

    来源用三个 0/1 标记列而不是字符串聚合：同一对 (caller, callee) 可能被多张表
    同时记录，标记列既能表达重叠，又不需要 ``string_agg(DISTINCT …)`` 那种排序开销
    （该 CTE 每次调用树请求都要跑一条）。
    """
    flags = ", ".join(
        f"max(CASE WHEN src = '{src}' THEN 1 ELSE 0 END) AS from_{src}" for src in SOURCES
    )
    return f"""
    WITH raw AS (
        {union}
    ), merged AS (
        SELECT caller, callee, max(detail) AS detail, {flags}
        FROM raw WHERE caller IS NOT NULL AND callee IS NOT NULL AND callee <> ''
        GROUP BY caller, callee
    ), {name} AS (
        SELECT merged.caller, merged.callee, merged.detail,
               merged.from_regex, merged.from_resolved, merged.from_framework,
               CASE
                   WHEN merged.callee LIKE '<%' THEN '{KIND_DYNAMIC}'
                   WHEN merged.callee LIKE '}}%' THEN '{KIND_FRAMEWORK}'
                   WHEN known.name IS NULL THEN '{KIND_MISSING}'
                   ELSE '{KIND_LITERAL}'
               END AS kind,
               -- 调用方自己也要分类：图上「谁调用我」显示的是调用方，
               -- 若把被调用方的 kind 贴到调用方身上，框架进程的 1996 个上游
               -- 会被全部标成「框架」，而它们其实是普通业务 TI。
               CASE
                   WHEN merged.caller LIKE '}}%' THEN '{KIND_FRAMEWORK}'
                   WHEN known_caller.name IS NULL THEN '{KIND_MISSING}'
                   ELSE '{KIND_LITERAL}'
               END AS caller_kind
        FROM merged
        -- processes.name 是主键，直接连接不会放大行数；用子查询 + DISTINCT 会多花约 13 ms。
        LEFT JOIN processes AS known ON known.name = merged.callee
        LEFT JOIN processes AS known_caller ON known_caller.name = merged.caller
    )
    """


_EMPTY_CTE = (
    "WITH {name} AS (SELECT CAST(NULL AS VARCHAR) AS caller, CAST(NULL AS VARCHAR) AS callee,"
    " CAST(NULL AS VARCHAR) AS detail, CAST(NULL AS VARCHAR) AS kind,"
    " CAST(NULL AS VARCHAR) AS caller_kind,"
    " CAST(0 AS INTEGER) AS from_regex, CAST(0 AS INTEGER) AS from_resolved,"
    " CAST(0 AS INTEGER) AS from_framework WHERE FALSE)"
)


def primary_source(from_regex: int, from_resolved: int, from_framework: int) -> str | None:
    """同一对 (caller, callee) 被多张表记录时，给出最硬的那一份证据。"""
    present = {
        SRC_REGEX: from_regex, SRC_RESOLVED: from_resolved, SRC_FRAMEWORK: from_framework,
    }
    for src in _SOURCE_RANK:
        if present.get(src):
            return src
    return None


def sources_of(from_regex: int, from_resolved: int, from_framework: int) -> list[str]:
    """这条边被哪些来源记录（可能不止一张表）。"""
    present = {
        SRC_REGEX: from_regex, SRC_RESOLVED: from_resolved, SRC_FRAMEWORK: from_framework,
    }
    return [src for src in SOURCES if present.get(src)]


def edges_cte(con: duckdb.DuckDBPyConnection, name: str = "call_edge") -> str:
    """生成 ``WITH <name> AS (...)`` 片段，供本模块与调用树共用同一份口径。

    结果列：``caller`` / ``callee`` / ``kind`` / ``detail`` /
    ``from_regex`` / ``from_resolved`` / ``from_framework``。
    同一 (caller, callee) 在两张表都出现时只保留一行，``detail`` 取非空的一侧，
    来源标记各自保留。
    """
    present = available_sources(con)
    parts = [sql for table, sql, _ in _SOURCES if table in present]
    if not parts:
        # 没有任何来源表：给一个空集合，调用方仍能正常工作。
        return _EMPTY_CTE.format(name=name)
    return _classify_cte(" UNION ALL ".join(parts), name)


def object_edges_cte(con: duckdb.DuckDBPyConnection, process: str, alias: str = "call_edge") -> tuple[str, list[str]]:
    """单个 TI 的上下游边（过滤下推到表扫描，不先合并全模型），返回 ``(CTE 文本, 参数量)``。

    每个来源表贡献两个占位符（左侧 caller / 右侧 callee），因此调用方传入的
    参数就是 ``[process, process] × 来源表数量``。
    """
    present = available_sources(con)
    parts = [filtered for table, _, filtered in _SOURCES if table in present]
    if not parts:
        return _EMPTY_CTE.format(name=alias), []
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
        + " SELECT DISTINCT caller, callee, kind, caller_kind, detail,"
          " from_regex, from_resolved, from_framework FROM call_edge"
        + clause
        + " ORDER BY callee, caller",
        params,
    ).fetchall()
    return [
        {
            "caller": r[0], "callee": r[1], "kind": r[2], "caller_kind": r[3], "detail": r[4],
            "source": primary_source(r[5], r[6], r[7]),
            "sources": sources_of(r[5], r[6], r[7]),
        }
        for r in rows
    ]


def summary(con: duckdb.DuckDBPyConnection, name: str) -> dict:
    """一个 TI 的调用事实摘要：谁调用它（已确认集合）+ 它调用谁（按 kind 分类）。

    ``callers`` 是**去重后的调用方进程名**。调用方本身必定是目录里的 TI
    （采集只记录真实进程名），因此这里不需要再分 kind。

    ``callers_by_source`` / ``callees_by_source`` 回答「这个数字凭什么」：
    按产出它的表分别计数。三张表会重叠（同一次调用可能被正则和框架表同时记录），
    所以各来源之和 ≥ 去重后的总数；页面必须把这层写清楚，不能让人把两个数相加。

    ``dynamic_callees`` 是「有几处调用目标没能解析成固定成员」——一个计数，
    不是进程名列表；这些目标可能是任何 TI，不能点名。

    ``callers_business`` / ``callers_system`` 与 ``callees_by_scope`` 是同一份事实的
    范围拆分，供页面默认「只看业务对象」时如实报出被折叠的数量（折叠必须显式，
    不能让人以为系统对象不存在）。
    """
    empty_sources = {src: 0 for src in SOURCES}
    if is_dynamic_target(name):
        # 占位名不是成员：不存在「谁调用 <sProc2>」这种事实，直接返回空集。
        return {"callers": [], "callees": [],
                "counts": {"callers": 0, "callees": {k: 0 for k in KINDS}},
                "callers_by_source": dict(empty_sources),
                "callees_by_source": dict(empty_sources),
                "callers_business": 0, "callers_system": 0,
                "callees_by_scope": {SCOPE_BUSINESS: 0, SCOPE_SYSTEM: 0, KIND_DYNAMIC: 0},
                "scope": KIND_DYNAMIC,
                "dynamic_callees": 0, "node_callees": []}
    # 过滤下推到三张表，只算这个 TI 的上下游；一条 SQL 同时拿到两个方向。
    cte, params = object_edges_cte(con, name)
    rows = con.execute(
        cte + " SELECT DISTINCT caller, callee, kind, caller_kind, detail,"
              " from_regex, from_resolved, from_framework FROM call_edge ORDER BY callee, caller",
        params,
    ).fetchall()
    inbound = [r for r in rows if r[1] == name]
    outbound = [r for r in rows if r[0] == name]
    callers = sorted({r[0] for r in inbound})
    counts = {kind: 0 for kind in KINDS}
    for row in outbound:
        counts[row[2]] = counts.get(row[2], 0) + 1

    # 按来源统计「去重后的调用方个数」：同一个调用方可能被多张表记录，必须按集合去重，
    # 不能把行数当个数（否则 131 + 1996 会算出重叠部分）。
    caller_sets = {src: set() for src in SOURCES}
    callee_sets = {src: set() for src in SOURCES}
    for row in inbound:
        for src in sources_of(row[5], row[6], row[7]):
            caller_sets[src].add(row[0])
    for row in outbound:
        for src in sources_of(row[5], row[6], row[7]):
            callee_sets[src].add(row[1])

    callees = [
        {"caller": r[0], "callee": r[1], "kind": r[2], "detail": r[4],
         "source": primary_source(r[5], r[6], r[7]),
         "sources": sources_of(r[5], r[6], r[7])}
        for r in sorted(outbound, key=lambda r: (KINDS.index(r[2]) if r[2] in KINDS else 99, r[1]))
    ]
    callees_by_scope = {SCOPE_BUSINESS: 0, SCOPE_SYSTEM: 0, KIND_DYNAMIC: 0}
    for edge in callees:
        if edge["kind"] == KIND_DYNAMIC:
            callees_by_scope[KIND_DYNAMIC] += 1
        elif is_system_object(edge["callee"]):
            callees_by_scope[SCOPE_SYSTEM] += 1
        else:
            callees_by_scope[SCOPE_BUSINESS] += 1
    return {
        "callers": callers,
        "callees": callees,
        "counts": {"callers": len(callers), "callees": counts},
        "callers_by_source": {src: len(caller_sets[src]) for src in SOURCES},
        "callees_by_source": {src: len(callee_sets[src]) for src in SOURCES},
        "callers_business": sum(1 for c in callers if not is_system_object(c)),
        "callers_system": sum(1 for c in callers if is_system_object(c)),
        "callees_by_scope": callees_by_scope,
        "scope": scope_of(name),
        "dynamic_callees": counts.get(KIND_DYNAMIC, 0),
        "node_callees": [e for e in callees if e["kind"] in NODE_KINDS],
    }


def caller_counts_by_target(con: duckdb.DuckDBPyConnection, limit: int | None = None) -> list[dict]:
    """全模型口径对照：每个被调用对象「正则扫到几个 / 合并后几个」。

    只读、单条 SQL。用途是把「页头数字为什么变了」摊开给人抽查，
    不是给业务做分析——因此不做趋势、不做聚合排序之外的加工。
    """
    rows = con.execute(
        edges_cte(con)
        + """
        SELECT callee,
               count(DISTINCT caller) FILTER (WHERE from_regex = 1) AS n_regex,
               count(DISTINCT caller) FILTER (WHERE from_resolved = 1) AS n_resolved,
               count(DISTINCT caller) FILTER (WHERE from_framework = 1) AS n_framework,
               count(DISTINCT caller) AS n_total
        FROM call_edge
        GROUP BY callee
        ORDER BY (n_total - n_regex) DESC, n_total DESC
        """
    ).fetchall()
    out = []
    for callee, n_regex, n_resolved, n_framework, n_total in rows:
        out.append({
            "callee": callee,
            "regex": n_regex,
            "resolved": n_resolved,
            "framework": n_framework,
            "total": n_total,
            "delta": n_total - n_regex,
            "dynamic": is_dynamic_target(callee),
            # 系统对象与业务对象分开统计：153 个差异里 19 个是 } 开头，
            # 页面默认只给业务对象，但必须报出被折叠的条数。
            "system": is_system_object(callee),
        })
    if limit is not None:
        return out[:limit]
    return out
