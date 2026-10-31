"""把已有快照收敛到「不收系统对象」的范围。

采集端（``ingest.scope``）从下一次采集起就不再拉 ``}`` 对象的正文。但已经采过的
库里仍然躺着一批 273 个 ``}bedrock.*`` / ``}Cubes``——它们会继续占据列表、
详情和统计。本模块负责把这类旧库对齐到同一个范围。

两条硬规矩：

1. **默认 dry-run**：只统计、只打印，不写一个字节。要用 ``--apply`` 才动库。
2. **删对象不删事实**：对象正文从 ``processes`` / ``cubes`` / ``dimensions`` 移除，
   名字写进 ``excluded_objects``；引用它们的调用边、读写关系一律保留——
   「这个 TI 调了 ``}bedrock.cube.data.clear``」不因为没采它的源码而变假。
"""
from __future__ import annotations

import duckdb

from tm1_insight.ingest.scope import EXCLUDED_REASON, is_system_object

#: 会被收敛的表（表名, 类型标签）。类型标签写进 excluded_objects.kind。
_TARGETS = (
    ("processes", "processes"),
    ("cubes", "cubes"),
    ("dimensions", "dimensions"),
)

#: 这些表记录了对象之间的引用，收敛对象时**不能**动它们。
#: 这里只列「目标列叫 callee」的三张调用表，用于统计会影响多少条调用边。
_REFERENCE_TABLES = ("process_calls_process", "ti_business_calls", "ti_framework_calls")


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1", [name]
    ).fetchone())


def survey(con: duckdb.DuckDBPyConnection) -> dict:
    """统计将要发生什么，不修改任何数据。"""
    counts: dict[str, int] = {}
    for table, _kind in _TARGETS:
        if not _table_exists(con, table):
            continue
        counts[table] = con.execute(
            f"SELECT count(*) FROM {table} WHERE name LIKE '}}%'").fetchone()[0]
    already = 0
    if _table_exists(con, "excluded_objects"):
        already = con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0]

    # 引用面：这些是「删掉对象后仍要保留」的边，报出来让人知道影响范围。
    referenced = {}
    for table in _REFERENCE_TABLES:
        if not _table_exists(con, table):
            continue
        referenced[table] = con.execute(
            f"SELECT count(*) FROM {table} WHERE callee LIKE '}}%'").fetchone()[0]

    return {
        "objects": counts,
        "object_total": sum(counts.values()),
        "already_excluded": already,
        "referencing_edges": referenced,
    }


def prune(con: duckdb.DuckDBPyConnection, apply: bool = False) -> dict:
    """把 ``}`` 开头的对象移出对象表，并把名字登记为「按范围未收录」。

    :param apply: False（默认）只返回统计；True 才真正写入。
    :return: ``{"applied": bool, "removed": {...}, "excluded": n, ...}``
    """
    report = survey(con)
    if not apply:
        return {"applied": False, **report}

    removed: dict[str, int] = {}
    names: list[tuple[str, str]] = []
    for table, kind in _TARGETS:
        if not _table_exists(con, table):
            continue
        rows = con.execute(f"SELECT name FROM {table} WHERE name LIKE '}}%'").fetchall()
        if not rows:
            continue
        names.extend((row[0], kind) for row in rows)
        con.execute(f"DELETE FROM {table} WHERE name LIKE '}}%'")
        removed[table] = len(rows)

    # 同一名字可能同时出现在进程/立方体/维度里（极少），按名字去重，先到先得。
    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for name, kind in names:
        if name in seen:
            continue
        seen.add(name)
        unique.append((name, kind, EXCLUDED_REASON))
    if unique:
        # 必须用 executemany：execute 会把整个列表当成一组参数，只写入第一行。
        con.executemany("INSERT OR REPLACE INTO excluded_objects VALUES (?, ?, ?)", unique)

    return {
        "applied": True,
        "removed": removed,
        "excluded": len(unique),
        "already_excluded": report["already_excluded"],
        "referencing_edges": report["referencing_edges"],
    }


def excluded_targets(con: duckdb.DuckDBPyConnection) -> set[str]:
    """当前库里被排除的对象名（供页面判断「未收录」而非「不存在」）。"""
    if not _table_exists(con, "excluded_objects"):
        return set()
    return {row[0] for row in con.execute("SELECT name FROM excluded_objects").fetchall()}


__all__ = ["survey", "prune", "excluded_targets", "is_system_object"]
