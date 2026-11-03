"""资产地图（atlas-1）：把本地已采集事实汇总成可解释的资产清单。

约束（见 PRODUCT_CONSTITUTION.md「资产提炼优先」）：

- 分数只由**可数的技术信号**相加得到，每一项信号都在界面上单独展示；它不是业务重要性评级。
- 未知不等于零：没有写入方的 Cube 会明确标注「未记录写入方」，而不是被静默排到末尾。
- 不按对象名称猜测业务含义；不引入任何外部 AI 服务。
- 只读：所有查询走 read_only 连接，不改动模型数据。
"""
from __future__ import annotations

import json
from typing import Iterable

SCHEMA = "atlas-1"

KINDS = ("cube", "process", "dimension", "chore")
KIND_LABELS = {
    "cube": "Cube",
    "process": "TI 进程",
    "dimension": "Dimension",
    "chore": "Chore",
}

# 每个信号的 (key, 标签, 权重, 解释)。权重只影响同一模型内的排序，不代表业务价值。
SIGNALS: dict[str, tuple[tuple[str, str, int, str], ...]] = {
    "cube": (
        ("writers", "写入 TI", 3, "直接向该 Cube 写数的 TI 数量（含清空、搬运、增量）"),
        ("readers", "读取 TI", 2, "从该 Cube 取数的 TI 数量（CellGet / 数据源视图）"),
        ("rule_refs", "Rule 引用", 2, "本 Cube 的 Rule 引用其它 Cube 的次数 + 被其它 Rule 引用的次数"),
        ("scheduled", "调度链", 2, "写入该 Cube 的 TI 被多少个 Chore 调度"),
        ("frontend", "前端页面", 3, "已采集的前端菜单 / Excel 资产里引用该 Cube 的页面数"),
        ("rules", "含 Rule", 1, "该 Cube 存在 Rule 文本，即存在计算逻辑"),
    ),
    "process": (
        ("writes", "写 Cube", 3, "该 TI 写入的 Cube 数量"),
        ("reads", "读 Cube", 2, "该 TI 读数的 Cube 数量"),
        ("callers", "被调用", 2, "有多少个 TI 调用它（上游入口）"),
        ("callees", "调用", 1, "它调用了多少个 TI（子过程）"),
        ("scheduled", "调度", 2, "被多少个 Chore 调度，即有无定时入口"),
    ),
    "dimension": (
        ("cubes", "被 Cube 使用", 3, "有多少个 Cube 用该维度作为坐标轴"),
        ("maintained", "被 TI 维护", 2, "有多少个 TI 维护该维度的元素或属性"),
        ("elements", "元素量级", 1, "元素数量的对数档位，反映粒度规模"),
    ),
    "chore": (
        ("steps", "步骤", 3, "该 Chore 编排的 TI 步骤数"),
    ),
}

SOURCE_NOTE = (
    "信号来自本地已采集索引（TI 读写、调用、Rule 引用、Chore 编排、前端映射）。"
    "未采集的对象不计入，也不代表不存在；分数只用于在同一模型内排序，不是业务重要性结论。"
)


# ---------------------------------------------------------------- helpers

def _safe_rows(con, sql: str) -> list[tuple]:
    """表或列缺失时返回空结果：旧库不应让整页报错。"""
    try:
        return con.execute(sql).fetchall()
    except Exception:  # noqa: BLE001
        return []


def _split_list(text: object) -> list[str]:
    """把 JSON 数组或逗号分隔的字段拆成字符串列表。"""
    if not text:
        return []
    raw = str(text).strip()
    if raw.startswith("["):
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return []
        return [str(v) for v in value] if isinstance(value, list) else []
    return [part.strip() for part in raw.split(",") if part.strip()]


def is_system(name: str) -> bool:
    return name.startswith("}")


def _score(kind: str, signals: dict[str, int]) -> int:
    return sum(weight * int(signals.get(key, 0)) for key, _label, weight, _note in SIGNALS[kind])


def _bucket(elements: int) -> int:
    """元素量级取 log 档位，避免超大维度把分数拉爆。"""
    level = 0
    size = max(int(elements or 0), 0)
    while size >= 10 and level < 6:
        size //= 10
        level += 1
    return level


def _chore_index(con) -> dict[str, set[str]]:
    """process -> 调度它的 chore 集合。"""
    index: dict[str, set[str]] = {}
    for name, processes in _safe_rows(con, "SELECT name, processes FROM chores"):
        for process in _split_list(processes):
            index.setdefault(process, set()).add(str(name))
    # chore_runs_process 在部分采集版本里可用，合并去重。
    for chore, process in _safe_rows(con, "SELECT chore_name, process_name FROM chore_runs_process"):
        index.setdefault(str(process), set()).add(str(chore))
    return index


# ---------------------------------------------------------------- builders

def _cube_items(con, include_system: bool) -> list[dict]:
    # 采集自不同来源的名称大小写可能不一致（前端映射常见全大写），
    # 统一用小写键匹配，避免真实存在的引用被算成 0。
    def keyed(sql: str) -> dict[str, int]:
        return {str(k).lower(): int(v) for k, v in _safe_rows(con, sql)}

    writers: dict[str, set[str]] = {}
    for process, cube in _safe_rows(con, "SELECT DISTINCT process_name, cube_name FROM process_writes_cube"):
        writers.setdefault(str(cube).lower(), set()).add(str(process))
    readers = keyed("SELECT lower(cube_name), COUNT(DISTINCT process_name) FROM process_reads_cube GROUP BY 1")
    rule_out = keyed("SELECT lower(cube_name), COUNT(DISTINCT source_cube) FROM rule_references_cube GROUP BY 1")
    rule_in = keyed("SELECT lower(source_cube), COUNT(DISTINCT cube_name) FROM rule_references_cube GROUP BY 1")
    frontend: dict[str, int] = {}
    for _menu, cubes_text in _safe_rows(con, "SELECT menu, backend_cubes FROM front_backend_mapping"):
        for cube in _split_list(cubes_text):
            key = cube.lower()
            frontend[key] = frontend.get(key, 0) + 1
    chores = _chore_index(con)

    items = []
    seen: set[str] = set()
    # 采集合并可能留下只有大小写不同的同名对象；按信息更全的一行保留，
    # 否则同一 Cube 会在清单里出现两次且分数不同（排序不稳定）。
    for name, has_rules, dimension_count in _safe_rows(
            con, "SELECT name, has_rules, dimension_count FROM cubes ORDER BY has_rules DESC, dimension_count DESC, name"):
        name = str(name)
        if not include_system and is_system(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cube_writers = writers.get(key, set())
        scheduled: set[str] = set()
        for process in cube_writers:
            scheduled |= chores.get(process, set())
        has_rule = 1 if has_rules else 0
        signals = {
            "writers": len(cube_writers),
            "readers": readers.get(key, 0),
            "rule_refs": rule_out.get(key, 0) + rule_in.get(key, 0),
            "scheduled": len(scheduled),
            "frontend": frontend.get(key, 0),
            "rules": has_rule,
        }
        notes = []
        if not cube_writers and has_rule:
            notes.append("只由 Rule 计算，索引里没有 TI 写入。")
        elif not cube_writers:
            notes.append("未记录写入方：可能是纯查询型 Cube、由外部接口写入，或本次采集未覆盖。")
        if cube_writers and not signals["readers"]:
            notes.append("没有已记录的读取 TI：下游可能通过视图、MDX 或前端直接访问。")
        items.append({
            "kind": "cube", "name": name, "score": _score("cube", signals),
            "signals": signals, "notes": notes,
            "meta": {"dimension_count": int(dimension_count or 0), "has_rules": bool(has_rules)},
        })
    return items


def _process_items(con, include_system: bool) -> list[dict]:
    def keyed(sql: str) -> dict[str, int]:
        return {str(k).lower(): int(n) for k, n in _safe_rows(con, sql)}

    write_counts = keyed("SELECT lower(process_name), COUNT(DISTINCT cube_name) FROM process_writes_cube GROUP BY 1")
    read_counts = keyed("SELECT lower(process_name), COUNT(DISTINCT cube_name) FROM process_reads_cube GROUP BY 1")
    callers = keyed("SELECT lower(callee), COUNT(DISTINCT caller) FROM process_calls_process GROUP BY 1")
    callees = keyed("SELECT lower(caller), COUNT(DISTINCT callee) FROM process_calls_process GROUP BY 1")
    chores = {str(k).lower(): v for k, v in _chore_index(con).items()}
    lengths = keyed("SELECT lower(name), code_length FROM processes")

    items = []
    seen: set[str] = set()
    for (name,) in _safe_rows(con, "SELECT name FROM processes ORDER BY (name = lower(name)), name"):
        name = str(name)
        if not include_system and is_system(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        signals = {
            "writes": write_counts.get(key, 0),
            "reads": read_counts.get(key, 0),
            "callers": callers.get(key, 0),
            "callees": callees.get(key, 0),
            "scheduled": len(chores.get(key, set())),
        }
        notes = []
        if not signals["writes"] and not signals["reads"]:
            notes.append("索引里没有读写 Cube 的记录：可能是维度维护、日志或纯计算过程。")
        if not signals["callers"] and not signals["scheduled"]:
            notes.append("没有已记录的调用方或调度入口：触发方式未知（可能来自外部调度或手工执行）。")
        items.append({
            "kind": "process", "name": name, "score": _score("process", signals),
            "signals": signals, "notes": notes,
            "meta": {"code_length": lengths.get(key, 0)},
        })
    return items


def _dimension_items(con, include_system: bool) -> list[dict]:
    cube_usage = {str(d): int(n) for d, n in _safe_rows(
        con, "SELECT dimension_name, COUNT(DISTINCT cube_name) FROM cube_has_dimension GROUP BY 1")}
    maintained = {str(d): int(n) for d, n in _safe_rows(
        con, "SELECT dimension_name, COUNT(DISTINCT process_name) FROM process_maintains_dimension GROUP BY 1")}
    rows = _safe_rows(con, "SELECT name, element_count, is_system FROM dimensions")

    items = []
    for name, element_count, system_flag in rows:
        name = str(name)
        if not include_system and (is_system(name) or system_flag):
            continue
        signals = {
            "cubes": cube_usage.get(name, 0),
            "maintained": maintained.get(name, 0),
            "elements": _bucket(int(element_count or 0)),
        }
        notes = [] if signals["cubes"] else ["没有任何 Cube 使用该维度：可能是未启用的草稿或纯属性维度。"]
        items.append({
            "kind": "dimension", "name": name, "score": _score("dimension", signals),
            "signals": signals, "notes": notes,
            "meta": {"element_count": int(element_count or 0)},
        })
    return items


def _chore_items(con, include_system: bool) -> list[dict]:
    items = []
    for name, process_count in _safe_rows(con, "SELECT name, process_count FROM chores"):
        name = str(name)
        if not include_system and is_system(name):
            continue
        signals = {"steps": int(process_count or 0)}
        items.append({
            "kind": "chore", "name": name, "score": _score("chore", signals),
            "signals": signals,
            "notes": [] if signals["steps"] else ["没有任何步骤：可能是占位或采集未包含步骤顺序。"],
            "meta": {},
        })
    return items


_BUILDERS = {
    "cube": _cube_items,
    "process": _process_items,
    "dimension": _dimension_items,
    "chore": _chore_items,
}


# ---------------------------------------------------------------- public API

def overview(con, include_system: bool = False) -> dict:
    """模型规模的稳定计数，与当前筛选无关。"""
    def counted(sql: str, system_sql: str) -> tuple[int, int]:
        total = (_safe_rows(con, sql) or [(0,)])[0][0] or 0
        system = (_safe_rows(con, system_sql) or [(0,)])[0][0] or 0
        return int(total), int(system)

    cubes_total, cubes_system = counted("SELECT COUNT(*) FROM cubes", "SELECT COUNT(*) FROM cubes WHERE name LIKE '}%'")
    processes_total, processes_system = counted("SELECT COUNT(*) FROM processes", "SELECT COUNT(*) FROM processes WHERE name LIKE '}%'")
    dims_total, dims_system = counted("SELECT COUNT(*) FROM dimensions", "SELECT COUNT(*) FROM dimensions WHERE name LIKE '}%'")
    chores_total, chores_system = counted("SELECT COUNT(*) FROM chores", "SELECT COUNT(*) FROM chores WHERE name LIKE '}%'")
    return {
        "cube": {"total": cubes_total, "system": cubes_system, "shown": cubes_total - cubes_system},
        "process": {"total": processes_total, "system": processes_system, "shown": processes_total - processes_system},
        "dimension": {"total": dims_total, "system": dims_system, "shown": dims_total - dims_system},
        "chore": {"total": chores_total, "system": chores_system, "shown": chores_total - chores_system},
    }


def gaps(con, include_system: bool = False, limit: int = 20) -> dict:
    """跨类型的覆盖缺口：这些对象最容易在盘点时被误读为「不存在」。"""
    writers = {str(c).lower() for (_p, c) in _safe_rows(
        con, "SELECT DISTINCT process_name, cube_name FROM process_writes_cube")}
    frontend = set()
    for _menu, cubes_text in _safe_rows(con, "SELECT menu, backend_cubes FROM front_backend_mapping"):
        frontend.update(cube.lower() for cube in _split_list(cubes_text))

    no_writer, no_frontend = [], []
    for (name,) in _safe_rows(con, "SELECT name FROM cubes ORDER BY name"):
        name = str(name)
        if not include_system and is_system(name):
            continue
        if name.lower() not in writers:
            no_writer.append(name)
        if name.lower() not in frontend:
            no_frontend.append(name)

    return {
        "cube_without_writer": {"count": len(no_writer), "sample": no_writer[:limit]},
        "cube_without_frontend": {"count": len(no_frontend), "sample": no_frontend[:limit]},
        "frontend_linked": len(frontend),
        "note": "缺口是「本次采集没记录」，不是「对象没用」。补充采集或人工确认后才能下结论。",
    }


SORT_KEYS = {"score", "name"}


def summary(con, kind: str = "cube", *, query: str = "", sort: str = "score",
            limit: int = 50, page: int = 1, include_system: bool = False) -> dict:
    """返回一页资产清单；分页与排序都在服务端完成，URL 即状态。"""
    kind = kind if kind in _BUILDERS else "cube"
    items = _BUILDERS[kind](con, include_system)

    keyword = (query or "").strip().lower()
    if keyword:
        items = [item for item in items if keyword in item["name"].lower()]

    signal_keys = {key for key, _l, _w, _n in SIGNALS[kind]}
    if sort in signal_keys or sort == "score":
        if sort != "score":
            items.sort(key=lambda i: (-i["signals"].get(sort, 0), -i["score"], i["name"]))
        else:
            items.sort(key=lambda i: (-i["score"], i["name"]))
    elif sort == "name":
        items.sort(key=lambda i: i["name"].lower())
    else:
        items.sort(key=lambda i: (-i["score"], i["name"]))

    total = len(items)
    limit = max(1, min(int(limit or 50), 500))
    pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * limit
    window = items[start:start + limit]

    # 分数条：以本页最高分为基准，纯视觉比例，不改变排序语义。
    peak = max([i["score"] for i in window], default=0) or 1
    for item in window:
        item["share"] = round(100 * item["score"] / peak) if item["score"] else 0

    return {
        "schema": SCHEMA,
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "signals": [
            {"key": key, "label": label, "weight": weight, "note": note}
            for key, label, weight, note in SIGNALS[kind]
        ],
        "items": window,
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
        "query": query or "",
        "sort": sort,
        "include_system": include_system,
        "source_note": SOURCE_NOTE,
    }


def position(con, kind: str, name: str, include_system: bool = False) -> dict | None:
    """单个对象在资产清单中的位置，供血缘/架构页显示「它在整个模型里的分量」。

    找不到时返回 None（对象不在已采集索引里），调用方不得编造排名。
    """
    kind = kind if kind in _BUILDERS else "cube"
    items = _BUILDERS[kind](con, include_system)
    items.sort(key=lambda i: (-i["score"], i["name"]))
    target = (name or "").strip().lower()
    total = len(items)
    for index, item in enumerate(items, 1):
        if item["name"].lower() == target:
            return {
                "kind": kind,
                "kind_label": KIND_LABELS[kind],
                "name": item["name"],
                "score": item["score"],
                "rank": index,
                "total": total,
                "notes": item["notes"],
                "signals": [
                    {"key": key, "label": label, "value": item["signals"].get(key, 0), "note": note}
                    for key, label, _weight, note in SIGNALS[kind]
                ],
            }
    return None


def _fmt_signals(kind: str, signals: dict[str, int]) -> str:
    cells = []
    for key, label, _weight, _note in SIGNALS[kind]:
        cells.append(f"{label} {signals.get(key, 0)}")
    return " · ".join(cells)


def export_markdown(con, kind: str = "cube", *, limit: int = 100, include_system: bool = False) -> str:
    """人类可直接带走的资产清单（Markdown），不是机器证据包。"""
    kind = kind if kind in _BUILDERS else "cube"
    data = summary(con, kind, limit=limit, page=1, include_system=include_system)
    counts = overview(con, include_system)
    gap = gaps(con, include_system)
    label = KIND_LABELS[kind]

    lines = [
        f"# {label} 资产清单",
        "",
        f"- 模型规模：{counts['cube']['shown']} Cube · {counts['process']['shown']} TI · "
        f"{counts['dimension']['shown']} Dimension · {counts['chore']['shown']} Chore"
        f"{'' if include_system else '（已排除 } 开头的系统对象）'}",
        f"- 本清单：按信号分排序的前 {len(data['items'])} 个 {label}，共 {data['total']} 个",
        f"- 口径：{SOURCE_NOTE}",
        "",
        f"## 排序信号（{label}）",
        "",
        "| 信号 | 权重 | 说明 |",
        "| --- | --- | --- |",
    ]
    for signal in data["signals"]:
        lines.append(f"| {signal['label']} | {signal['weight']} | {signal['note']} |")

    lines += ["", f"## {label} 清单", ""]
    header = "| # | 名称 | 信号分 | " + " | ".join(s["label"] for s in data["signals"]) + " | 备注 |"
    lines.append(header)
    lines.append("|" + " --- |" * (len(data["signals"]) + 3))
    for index, item in enumerate(data["items"], 1):
        cells = " | ".join(str(item["signals"].get(s["key"], 0)) for s in data["signals"])
        note = "；".join(item["notes"]).replace("|", "/")
        lines.append(f"| {index} | `{item['name']}` | {item['score']} | {cells} | {note} |")

    lines += [
        "",
        "## 覆盖缺口",
        "",
        f"- 无已记录写入方的 Cube：{gap['cube_without_writer']['count']} 个",
        f"- 无已采集前端引用的 Cube：{gap['cube_without_frontend']['count']} 个",
        f"- 已采集前端映射关联到的 Cube：{gap['frontend_linked']} 个",
        f"- {gap['note']}",
        "",
        "_本清单为静态索引统计，不代表运行时结果；业务含义需要人工确认。_",
    ]
    return "\n".join(lines) + "\n"
