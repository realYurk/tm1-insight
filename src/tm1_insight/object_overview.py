"""One object, one page: the read-only facts behind the object workbench.

This module answers, for a single Cube or TI, the four questions a reader
actually has: what is it, what depends on it, how is its value produced, and
what is not known. It never infers business meaning and never claims runtime
verification; every number comes from an indexed relation or a recorded field.
"""

from __future__ import annotations

import json
from typing import Any

from tm1_insight import atlas

KIND_LABELS = {"cube": "Cube", "process": "TI 进程"}
VIEWS = {
    "cube": (("overview", "概览"), ("graph", "关系图"), ("formation", "数据形成"), ("code", "实现"), ("handoff", "交接")),
    "process": (("overview", "概览"), ("graph", "调用关系"), ("code", "实现"), ("handoff", "交接")),
}


def _rows(con, sql: str, params: list | None = None) -> list[tuple]:
    """A missing table or column degrades one fact, never the whole page."""
    try:
        return con.execute(sql, params or []).fetchall()
    except Exception:  # noqa: BLE001
        return []


def _names(con, sql: str, params: list) -> list[str]:
    return [str(r[0]) for r in _rows(con, sql, params) if r and r[0]]


def _json_list(text: Any) -> list[str]:
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        return [str(x) for x in text]
    try:
        value = json.loads(text)
    except Exception:  # noqa: BLE001
        return [x.strip() for x in str(text).split(",") if x.strip()]
    return [str(x) for x in value] if isinstance(value, list) else []


def _frontend_pages(con) -> dict[str, list[str]]:
    """menu → cubes. Frontend mappings are recorded facts, not live usage."""
    pages: dict[str, list[str]] = {}
    for menu, cubes_text in _rows(con, "SELECT menu, backend_cubes FROM front_backend_mapping"):
        key = str(menu)
        for cube in _json_list(cubes_text):
            pages.setdefault(cube.lower(), []).append(key)
    return pages


def _chores_for(con, processes: list[str]) -> list[str]:
    if not processes:
        return []
    marks = ",".join("?" for _ in processes)
    lowered = [p.lower() for p in processes]
    return sorted({str(r[0]) for r in _rows(
        con, f"SELECT DISTINCT chore_name FROM chore_runs_process WHERE lower(process_name) IN ({marks})", lowered)})


def _cube(con, name: str, issues: list[str]) -> dict | None:
    row = None
    for r in _rows(con, "SELECT name, dimensions, rules, has_rules, dimension_count FROM cubes WHERE lower(name)=lower(?) "
                        "ORDER BY has_rules DESC, dimension_count DESC, (name = lower(name)), name", [name]):
        row = r
        break
    if row is None:
        return None
    real_name = str(row[0])
    dimensions = _json_list(row[1])
    rules_text = str(row[2] or "")
    has_rules = bool(row[3]) or bool(rules_text.strip())
    dim_count = int(row[4] or len(dimensions))

    writers = sorted(set(_names(con, "SELECT DISTINCT process_name FROM process_writes_cube WHERE lower(cube_name)=lower(?)", [real_name])))
    readers = sorted(set(_names(con, "SELECT DISTINCT process_name FROM process_reads_cube WHERE lower(cube_name)=lower(?)", [real_name])))
    rule_sources = sorted(set(_names(con, "SELECT DISTINCT source_cube FROM rule_references_cube WHERE lower(cube_name)=lower(?)", [real_name])))
    rule_targets = sorted(set(_names(con, "SELECT DISTINCT cube_name FROM rule_references_cube WHERE lower(source_cube)=lower(?)", [real_name])))
    chores = _chores_for(con, writers)
    pages = _frontend_pages(con).get(real_name.lower(), [])

    upstream = sorted(set(rule_sources) | set(_names(
        con, "SELECT DISTINCT cube_name FROM process_reads_cube WHERE process_name IN (SELECT process_name FROM process_writes_cube WHERE lower(cube_name)=lower(?))", [real_name])))
    downstream = set(rule_targets) | set(_names(
        con, "SELECT DISTINCT cube_name FROM process_writes_cube WHERE process_name IN (SELECT process_name FROM process_reads_cube WHERE lower(cube_name)=lower(?))", [real_name]))
    downstream -= set(upstream)
    downstream.discard(real_name)

    facts = [
        {"key": "dimensions", "label": "维度", "value": dim_count},
        {"key": "writers", "label": "写入 TI", "value": len(writers)},
        {"key": "readers", "label": "读取 TI", "value": len(readers)},
        {"key": "rule_refs", "label": "Rule 引用", "value": len(rule_sources) + len(rule_targets)},
        {"key": "schedules", "label": "调度 Chore", "value": len(chores)},
        {"key": "frontend", "label": "前端页面", "value": len(pages)},
    ]

    if writers:
        answer = f"数据由 {len(writers)} 个 TI 写入" + (f"，其中 {len(chores)} 个已进入调度" if chores else "，索引里没有调度记录") + "。"
    elif has_rules and rule_sources:
        answer = "索引里没有 TI 写入，值由 Rule 从其他 Cube 计算得到。"
    elif has_rules:
        answer = "索引里没有 TI 写入，Cube 含 Rule，计算来源未记录。"
    else:
        answer = "索引里没有写入方，可能是查询型 Cube，或采集未覆盖写入路径。"
        issues.append("未记录写入方：这既不是“无用”，也不证明没有数据。")

    if dimensions:
        answer += f" {dim_count} 个维度：" + "、".join(dimensions[:6]) + ("…" if len(dimensions) > 6 else "") + "。"

    if not pages:
        issues.append("前端映射中没有页面引用：可能只被其他 TI 或 Rule 使用。")
    if not upstream and not downstream and not has_rules:
        issues.append("上下游都没有已索引关系：先确认维度与元素是否被别处引用。")

    return {
        "kind": "cube",
        "kind_label": "Cube",
        "name": real_name,
        "answer": answer,
        "facts": facts,
        "dimensions": dimensions,
        "writers": writers,
        "readers": readers,
        "upstream": upstream[:12],
        "downstream": sorted(downstream)[:12],
        "rule_sources": rule_sources,
        "chores": chores,
        "pages": sorted(set(pages)),
        "has_rules": has_rules,
        "rules_text": rules_text,
        "issues": issues,
        "source": "MODEL_FACT",
    }


def _process(con, name: str, issues: list[str]) -> dict | None:
    row = None
    for r in _rows(con, "SELECT name, prolog, metadata, data, epilog, parameters, code_length FROM processes "
                        "WHERE lower(name)=lower(?) ORDER BY (name = lower(name)), name", [name]):
        row = r
        break
    if row is None:
        return None
    real_name = str(row[0])
    sections = {"prolog": str(row[1] or ""), "metadata": str(row[2] or ""), "data": str(row[3] or ""), "epilog": str(row[4] or "")}
    try:
        parameters = json.loads(row[5] or "[]")
    except Exception:  # noqa: BLE001
        parameters = []
    code_length = int(row[6] or sum(len(v) for v in sections.values()))

    writes = sorted(set(_names(con, "SELECT DISTINCT cube_name FROM process_writes_cube WHERE lower(process_name)=lower(?)", [real_name])))
    reads = sorted(set(_names(con, "SELECT DISTINCT cube_name FROM process_reads_cube WHERE lower(process_name)=lower(?)", [real_name])))
    callers = sorted(set(_names(con, "SELECT DISTINCT caller FROM process_calls_process WHERE lower(callee)=lower(?)", [real_name])))
    callees = sorted(set(_names(con, "SELECT DISTINCT callee FROM process_calls_process WHERE lower(caller)=lower(?)", [real_name])))
    chores = _chores_for(con, [real_name])

    facts = [
        {"key": "writes", "label": "写入 Cube", "value": len(writes)},
        {"key": "reads", "label": "读取 Cube", "value": len(reads)},
        {"key": "callees", "label": "调用 TI", "value": len(callees)},
        {"key": "schedules", "label": "调度 Chore", "value": len(chores)},
        {"key": "parameters", "label": "参数", "value": len(parameters) if isinstance(parameters, list) else 0},
        {"key": "lines", "label": "代码字符", "value": code_length},
    ]

    if writes:
        answer = "把数据写进 " + "、".join(writes[:5]) + ("…" if len(writes) > 5 else "") + "。"
    else:
        answer = "索引里没有写入的 Cube：可能是校验、导出或调度控制类进程。"
        issues.append("没有写入目标：确认它是否只做校验、导出或调用其他 TI。")
    if reads:
        answer += " 读取 " + "、".join(reads[:5]) + ("…" if len(reads) > 5 else "") + "。"
    if callees:
        answer += f" 调用 {len(callees)} 个子 TI。"
    if chores:
        answer += " 由 " + "、".join(chores[:3]) + " 调度。"
    else:
        issues.append("没有已索引的调度记录：不能据此认定只能手动运行。")

    return {
        "kind": "process",
        "kind_label": "TI 进程",
        "name": real_name,
        "answer": answer,
        "facts": facts,
        "sections": sections,
        "parameters": parameters if isinstance(parameters, list) else [],
        "writes": writes,
        "reads": reads,
        "upstream": reads[:12],
        "downstream": writes[:12],
        "callers": callers,
        "callees": callees,
        "chores": chores,
        "issues": issues,
        "source": "MODEL_FACT",
    }


def build(con, kind: str, name: str) -> dict | None:
    """Assemble one object's page facts. Returns None when the object is absent."""
    kind = kind if kind in KIND_LABELS else "cube"
    issues: list[str] = []
    data = _cube(con, name, issues) if kind == "cube" else _process(con, name, issues)
    if data is None:
        return None
    try:
        data["position"] = atlas.position(con, kind, data["name"])
    except Exception:  # noqa: BLE001
        data["position"] = None
    data["views"] = VIEWS[kind]
    data["issues"] = issues[:4]
    return data


def source(con, kind: str, name: str) -> dict:
    """Implementation payload: Rule text for a Cube, four sections for a TI."""
    if kind == "cube":
        for row in _rows(con, "SELECT name, rules FROM cubes WHERE lower(name)=lower(?)", [name]):
            return {"rules": str(row[1] or "")}
        return {"rules": ""}
    for row in _rows(con, "SELECT prolog, metadata, data, epilog FROM processes WHERE lower(name)=lower(?)", [name]):
        return {"prolog": str(row[0] or ""), "metadata": str(row[1] or ""), "data": str(row[2] or ""), "epilog": str(row[3] or "")}
    return {}


def _join(items: list[str], limit: int = 12) -> str:
    if not items:
        return ""
    head = "、".join(items[:limit])
    return head + (f" 等 {len(items)} 个" if len(items) > limit else "")


def handoff_markdown(item: dict) -> str:
    """The take-away page: readable in a review, no second pass required."""
    lines = [
        f"# {item['kind_label']} · {item['name']}",
        "",
        item["answer"],
        "",
        "## 关键事实",
        "",
        "| 项 | 值 |",
        "|---|---|",
    ]
    for fact in item["facts"]:
        lines.append(f"| {fact['label']} | {fact['value']} |")
    lines += ["", "## 上下游", ""]
    lines.append("- 上游：" + (_join(item["upstream"]) or "无已索引来源"))
    lines.append("- 下游：" + (_join(item["downstream"]) or "无已索引去向"))
    if item["kind"] == "cube":
        lines.append("- 写入 TI：" + (_join(item["writers"]) or "未记录"))
        lines.append("- 读取 TI：" + (_join(item["readers"]) or "未记录"))
        lines.append("- 前端页面：" + (_join(item["pages"]) or "未记录"))
    else:
        lines.append("- 调用方：" + (_join(item["callers"]) or "未记录"))
        lines.append("- 子进程：" + (_join(item["callees"]) or "无"))
    if item["chores"]:
        lines += ["", "## 调度", "", "、".join(item["chores"])]
    if item["issues"]:
        lines += ["", "## 未知与边界", ""] + [f"- {note}" for note in item["issues"]]
    lines += [
        "",
        "## 口径",
        "",
        "以上全部来自本地已采集的静态元数据与解析索引；未执行 TI，不代表运行时结果，也不代表业务含义。",
        f"资产信号：{item['position']['score']}（模型内第 {item['position']['rank']} / {item['position']['total']} 位，仅用于发现，不代表业务重要度）。" if item.get("position") else "资产信号：该对象不在已排序的资产清单中。",
        "",
    ]
    return "\n".join(lines)
