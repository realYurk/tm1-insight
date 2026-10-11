"""Web API wiring：把 DuckDB 里的关系表适配成分析引擎需要的输入。

这是一个**薄适配层**，只负责「把现有 Store 数据转换成 Dependency / Snapshot
payload」，让 Web 层能复用已实现的纯函数引擎（impact / compare /
change_intelligence），**不重新实现任何图算法 / Compare / Impact**。

数据源映射（对齐 store/schema.py 的 relation 表）：
- process_reads_cube  → Dependency(PROCESS_READS_CUBE, process, cube)
- process_writes_cube → Dependency(PROCESS_WRITES_CUBE, process, cube)
- process_calls_process → Dependency(PROCESS_CALLS_PROCESS, caller, callee)
- rule_references_cube  → Dependency(RULE_REFERENCES_CUBE, cube, source_cube)
"""
from __future__ import annotations

import json

import duckdb

from tm1_insight.domain.model import Dependency, DependencyKind


# ---------------------------------------------------------------------------
# DuckDB → Dependency
# ---------------------------------------------------------------------------

def dependencies_from_store(con: duckdb.DuckDBPyConnection) -> list[Dependency]:
    """从 DuckDB relation 表构建确定性、去重后的 Dependency 列表。

    只读现有表，不写库、不重新 ingest。目标无法确定（空名）时不产出依赖。
    """
    deps: dict[tuple, Dependency] = {}

    def _add(kind: DependencyKind, source: str, target: str) -> None:
        if not source or not target:
            return
        key = (kind, source, target)
        if key not in deps:
            deps[key] = Dependency(kind=kind, source=source, target=target)

    # Process → Cube（读 / 写）
    for (process_name, cube_name) in con.execute(
        "SELECT process_name, cube_name FROM process_reads_cube"
    ).fetchall():
        _add(DependencyKind.PROCESS_READS_CUBE, process_name, cube_name)
    for (process_name, cube_name) in con.execute(
        "SELECT process_name, cube_name FROM process_writes_cube"
    ).fetchall():
        _add(DependencyKind.PROCESS_WRITES_CUBE, process_name, cube_name)

    # Process → Process（调用）
    for (caller, callee) in con.execute(
        "SELECT caller, callee FROM process_calls_process"
    ).fetchall():
        _add(DependencyKind.PROCESS_CALLS_PROCESS, caller, callee)

    # Rule → Cube（跨 cube 引用）
    for (cube_name, source_cube) in con.execute(
        "SELECT cube_name, source_cube FROM rule_references_cube"
    ).fetchall():
        _add(DependencyKind.RULE_REFERENCES_CUBE, cube_name, source_cube)

    result = list(deps.values())
    result.sort(key=lambda d: (d.kind.value, d.source, d.target))
    return result


# ---------------------------------------------------------------------------
# DuckDB → Snapshot payload（供 Compare / Change Intelligence）
# ---------------------------------------------------------------------------

def snapshot_payload_from_store(con: duckdb.DuckDBPyConnection) -> dict:
    """把当前 DuckDB 内容构建成 canonical snapshot payload。

    复用 snapshot/schema.py 的 payload 结构（processes / rules / cubes /
    dimensions 四个 collection），供 compare_snapshots / analyze_changes 消费。
    只读库，不修改、不重新 ingest。
    """
    processes = [
        {"name": r[0], "prolog": r[1] or "", "metadata": r[2] or "",
         "data": r[3] or "", "epilog": r[4] or ""}
        for r in con.execute(
            "SELECT name, prolog, metadata, data, epilog FROM processes ORDER BY name"
        ).fetchall()
    ]

    cubes = [
        {"name": r[0], "dimensions": json.loads(r[1]) if r[1] else [],
         "rules": [r[2]] if r[2] else []}
        for r in con.execute(
            "SELECT name, dimensions, rules FROM cubes ORDER BY name"
        ).fetchall()
    ]

    dimensions = [
        {"name": r[0], "elements": [], "subsets": []}
        for r in con.execute("SELECT name FROM dimensions ORDER BY name").fetchall()
    ]

    rules = []
    for (cube_name, source_cube) in con.execute(
        "SELECT DISTINCT cube_name, source_cube FROM rule_references_cube ORDER BY 1, 2"
    ).fetchall():
        rules.append({
            "cube": cube_name,
            "statement": f"[{cube_name}] -> [{source_cube}]",
            "referenced_cubes": [source_cube],
        })

    return {
        "processes": processes,
        "rules": rules,
        "cubes": cubes,
        "dimensions": dimensions,
    }
