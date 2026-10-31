"""真实库端到端巡检：范围这条线（2C→2I）在真实数据上到底对不对得上。

不是单元测试——它需要一份真实采集库，所以不进 pytest 默认收集。
跑法（只读，不改 data/）：

    TM1_INSIGHT_DATA_DIR=<abs>/data ./.venv/Scripts/python.exe tests/audit_scope_e2e.py

检查的都是一致性，不是「数字长什么样」：
  1. 前端口径：状态条说的条数 == 列表实际渲染的条数 == 导出文件里的条数
  2. 切到全量后条数单调增加，且增加量恰好等于状态条说的隐藏量
  3. 编号不重编：可见写入点的 id 是全量 id 的子序列
  4. 读取依赖：read_nodes 完整、reads_shown 是子集、提示文案与计数对得上
  5. 调用树：每个标了位置的节点，位置行确实含被调用名
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from tm1_insight.config import get_settings  # noqa: E402
from tm1_insight.store import calculation, scope_view  # noqa: E402

PROBLEMS: list[str] = []
CHECKED = {"ti": 0, "writes": 0, "reads": 0, "tree": 0}


def bad(kind: str, name: str, detail: str) -> None:
    PROBLEMS.append(f"[{kind}] {name} · {detail}")


def audit_calculation(con, name: str) -> None:
    report = calculation.inspect(con, name)
    if not report or not report["writes"]:
        return
    CHECKED["ti"] += 1
    CHECKED["writes"] += len(report["writes"])

    view, info = scope_view.narrow_report(report, False)
    full, info_full = scope_view.narrow_report(report, True)

    # 1. 条数守恒：可见 + 隐藏 == 全量
    if info["visible"] + info["hidden"] != len(report["writes"]):
        bad("计数", name, f"可见 {info['visible']} + 隐藏 {info['hidden']} != 全量 {len(report['writes'])}")
    if info_full["visible"] != len(report["writes"]):
        bad("计数", name, f"全量视图 {info_full['visible']} != 报告 {len(report['writes'])}")

    # 2. 编号不重编：可见 id 必须是全量 id 的子序列，且顺序保持
    full_ids = [w["id"] for w in report["writes"]]
    keep_ids = [w["id"] for w in view["writes"]]
    if keep_ids != [i for i in full_ids if i in set(keep_ids)]:
        bad("编号", name, "可见写入点的 id 顺序被打乱，跳号对不上")

    # 3. 分类自洽：hidden == log + system
    if info["hidden"] != info["log"] + info["system"]:
        bad("分类", name, f"hidden {info['hidden']} != log {info['log']} + system {info['system']}")

    # 4. write_ids 与 kept 互补
    hidden_ids = set(info["write_ids"])
    if hidden_ids & set(keep_ids):
        bad("分类", name, f"同一个写入点既可见又被隐藏：{sorted(hidden_ids & set(keep_ids))[:5]}")
    if len(hidden_ids) != info["hidden"]:
        bad("分类", name, f"write_ids {len(hidden_ids)} 条 != hidden {info['hidden']}")

    # 5. 读取依赖：read_nodes 不裁剪、reads_shown ⊆ read_nodes
    for w in view["writes"]:
        nodes = w.get("read_nodes") or []
        shown = w.get("reads_shown")
        if shown is None:
            continue
        CHECKED["reads"] += len(nodes)
        if not set(shown) <= set(nodes):
            bad("读取", name, f"写入 {w['id']} 的 reads_shown 不在 read_nodes 里")
        if len(nodes) != len(shown) + len(w.get("reads_hidden") or []):
            bad("读取", name, f"写入 {w['id']}：read_nodes {len(nodes)} != shown {len(shown)} + hidden {len(w.get('reads_hidden') or [])}")

    # 6. 导出口径与页面口径一致（同一个函数产出的账本必须相同）
    if view["scope_view"] != info:
        bad("导出", name, "视图里的 scope_view 与单独算出来的账本不一致")

    # 7. 文案与计数对得上：说了 N 条就必须真有 N 条
    text = scope_view.hidden_text(info, "写入点")
    if info["hidden"] and str(info["hidden"]) not in text:
        bad("文案", name, f"提示里没有出现隐藏条数 {info['hidden']}：{text[:60]}")
    if not info["hidden"] and "未显示" in text:
        bad("文案", name, f"没有隐藏却说有：{text[:60]}")


def audit_tree(con, name: str) -> None:
    from tm1_insight.store import call_sites, queries

    tree = queries.process_call_tree(con, name, max_depth=6, max_breadth=12,
                                     root_breadth=12, max_nodes=150, include_system=False)
    call_sites.attach(con, tree)
    CHECKED["tree"] += 1
    if tree.get("site_unlocated"):
        problem = [n for n in tree["callers"] + tree["callees"] if not n.get("site")]
        # 未定位必须被数出来，且总数等于实际缺位置的节点数
        if tree["site_unlocated"] != len(problem):
            bad("树", name, f"未定位计数 {tree['site_unlocated']} != 实际缺位置 {len(problem)}")
    for node in tree["callers"] + tree["callees"]:
        site = node.get("site")
        if not site:
            continue
        if not site.get("process"):
            bad("树", name, f"节点 {node['name']} 有位置却没记是哪份源码")
            continue
        row = con.execute("SELECT prolog,metadata,data,epilog FROM processes WHERE name=?",
                          [site["process"]]).fetchone()
        if not row:
            bad("树", name, f"位置所指的 TI {site['process']} 不在库里")
            continue
        sections = dict(zip(call_sites.SECTIONS, row))
        code = sections.get(site["section"]) or ""
        lines = code.split("\n")
        if site["line"] > len(lines):
            bad("树", name, f"{site['process']}:{site['line']} 超出源码行数 {len(lines)}")
            continue
        line = lines[site["line"] - 1]
        head = line.lower()
        if "executeprocess" not in head and "runprocess" not in head:
            bad("树", name, f"{site['process']}:{site['line']} 不是调用行：{line.strip()[:60]}")


def main() -> int:
    settings = get_settings()
    db = settings.db_path
    if not db.exists():
        print(f"没有找到库：{db}")
        return 2
    print(f"库：{db}  ({db.stat().st_size / 1e9:.2f} GB)")
    con = duckdb.connect(str(db), read_only=True)

    names = [r[0] for r in con.execute(
        "SELECT name FROM processes WHERE NOT starts_with(name,'}') ORDER BY name").fetchall()]
    print(f"业务 TI：{len(names)}")

    # 挑「有系统写入」与「有系统读取」的真实样本，这两类才会触发范围逻辑
    src = ("lower(coalesce(prolog,'')||coalesce(metadata,'')||coalesce(data,'')||coalesce(epilog,''))")
    with_writes = [r[0] for r in con.execute(
        "SELECT name FROM processes WHERE NOT starts_with(name,'}') AND "
        + src + " LIKE '%cellput%''}%' ORDER BY length(name) LIMIT 40").fetchall()]
    with_reads = [r[0] for r in con.execute(
        "SELECT name FROM processes WHERE NOT starts_with(name,'}') AND "
        + src + " LIKE '%cellget%''}%' ORDER BY length(name) LIMIT 40").fetchall()]
    sample = list(dict.fromkeys(with_writes + with_reads))
    print(f"巡检样本：{len(sample)} 个 TI（有系统写入 {len(with_writes)}、有系统读取 {len(with_reads)}）\n")

    for name in sample:
        try:
            audit_calculation(con, name)
        except Exception as exc:  # noqa: BLE001
            bad("异常", name, f"{type(exc).__name__}: {exc}")

    for name in sample[:25]:
        try:
            audit_tree(con, name)
        except Exception as exc:  # noqa: BLE001
            bad("异常", name, f"调用树 {type(exc).__name__}: {exc}")

    con.close()
    print(f"检查：TI {CHECKED['ti']} 个、写入点 {CHECKED['writes']} 条、"
          f"读取依赖 {CHECKED['reads']} 条、调用树 {CHECKED['tree']} 棵")
    if not PROBLEMS:
        print("一致性：全部通过")
        return 0
    print(f"\n发现问题 {len(PROBLEMS)} 条：")
    for line in PROBLEMS[:40]:
        print("  ", line)
    return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
