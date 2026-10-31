"""Stage 0/1 — TI 源码查看路径的耗时分解与前后对比测量工具。

用途：给 `/explorer/process/{name}` 的「请求 → 可读源码」链路做可重复测量，
把总耗时拆成：连接 / SQL 次数 / 查询 / 解析 / 模板渲染 / 响应体积。

两种模型：
  synthetic  合成模型（默认）。在临时目录建独立 DuckDB，不读取也不写入 data/。
  live       可选。只读打开当前数据源库，跑真实进程名；只输出数值，不输出源码。

输出 JSON，便于前后对比。浏览器侧指标不在此处测量（无浏览器轨迹即记未测）。

用法：
  python scripts/measure_ti_source.py --model synthetic --out before.json
  python scripts/measure_ti_source.py --model live --process "<名称>" --iterations 10
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402

from tm1_insight.store.schema import ALL_TABLES  # noqa: E402
from tm1_insight.store import queries  # noqa: E402


# ---------------------------------------------------------------------------
# 合成模型：覆盖任务书要求的 6 类样本
# ---------------------------------------------------------------------------

def _ti_block(lines: int, *, cellput: bool = True, seed: int = 0) -> str:
    """生成确定性的 TI 代码行，语义无害（不连接任何服务器）。"""
    out = []
    for i in range(lines):
        k = (i + seed) % 6
        if k == 0:
            out.append(f"vAmount{i % 40} = CellGetN('Synthetic Cube', vYear, vPeriod, 'Measure{i % 5}');")
        elif k == 1:
            out.append(f"IF(vAmount{i % 40} @<> 0);")
        elif k == 2 and cellput:
            out.append(f"  CellPutN(vAmount{i % 40} * 1.05, 'Synthetic Target', vYear, vPeriod, 'Measure{i % 5}');")
        elif k == 3:
            out.append("ENDIF;")
        elif k == 4:
            out.append(f"# step {i}: 中文注释用于验证多字节渲染与行号定位")
        else:
            out.append(f"vLabel{i % 12} = '期间' | NumberToString(vPeriod);")
    return "\n".join(out)


def _loop_block(iterations: int) -> str:
    body = []
    for i in range(iterations):
        body.append(f"  CellPutN(vBase + {i}, 'Synthetic Target', vYear, vPeriod, 'Measure{i % 5}');")
    return "\n".join([
        "vIdx = 1;",
        "WHILE(vIdx <= 500);",
        *body,
        "  vIdx = vIdx + 1;",
        "END;",
    ])


LONG_NAME = "TI." + ".".join(["年度预算重算"] * 8) + ".明细到汇总.深度校验.合成样本"


def synthetic_spec() -> dict:
    """返回 {进程名: {...}} 的合成模型定义。"""
    normal = {"prolog": _ti_block(60, cellput=False), "data": _ti_block(110), "epilog": "# done"}
    long_ti = {"prolog": _ti_block(3000), "metadata": _ti_block(1500), "data": _ti_block(10000), "epilog": "# done"}
    multi = {"prolog": "vTag = 'dispatcher';", "data": _ti_block(80)}
    child = {"prolog": "vLeaf = 1;", "data": _ti_block(30)}
    hub = {"prolog": "vShared = CellGetN('Synthetic Cube', vYear, vPeriod, 'Shared');", "data": _ti_block(40)}
    loop = {"prolog": _ti_block(400), "data": _loop_block(1800)}
    longname = {"prolog": "vX = 1;", "data": _ti_block(58)}
    cyc_a = {"prolog": "vA = 1;", "data": _ti_block(20)}
    cyc_b = {"prolog": "vB = 2;", "data": _ti_block(20)}
    return {
        "Normal.LoadSales": normal,
        "Long.Reconciliation.Deep": long_ti,
        "Caller.Multi": multi,
        "Hub.Shared.Calc": hub,
        "Loop.While.Write": loop,
        LONG_NAME: longname,
        "Cycle.A": cyc_a,
        "Cycle.B": cyc_b,
        "__children__": {"Multi": [f"Multi.Child.{i}" for i in range(8)],
                         "Child": [f"Multi.Child.{i}.Grand.{j}" for i in range(8) for j in range(4)]},
        "__child_body__": child,
    }


def build_synthetic(db_path: Path) -> dict:
    """建合成库并返回「样本角色 → 进程名」映射。"""
    spec = synthetic_spec()
    meta = {"__children__", "__child_body__"}
    con = duckdb.connect(str(db_path))
    try:
        for ddl in ALL_TABLES.values():
            con.execute(ddl)

        cubes = ["Synthetic Cube", "Synthetic Target", "Synthetic Ignored"]
        for c in cubes:
            con.execute(
                "INSERT INTO cubes VALUES (?,?,?,?,?)",
                [c, json.dumps(["Year", "Period", "Measure"]), "", False, 3],
            )

        for name, body in spec.items():
            if name in meta:
                continue
            params = json.dumps([{"name": "pYear", "type": "String", "default_value": "2026"}])
            ds = json.dumps({"type": "TM1CubeView", "name": "Synthetic Cube"})
            con.execute(
                "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                [name, body.get("prolog", ""), body.get("metadata", ""), body.get("data", ""),
                 body.get("epilog", ""), params, ds, sum(len(v) for v in body.values())],
            )
            con.execute("INSERT INTO process_reads_cube VALUES (?,?)", [name, "Synthetic Cube"])
            con.execute("INSERT INTO process_writes_cube VALUES (?,?)", [name, "Synthetic Target"])
            con.execute("INSERT INTO process_reads_cube VALUES (?,?)", [name, "Synthetic Ignored"])

        # 多调用扇出：Caller.Multi -> 8 child -> 4 grandchild
        body = spec["__child_body__"]
        for i in range(8):
            con.execute(
                "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                [f"Multi.Child.{i}", body["prolog"], "", body["data"], "", "[]", "", 1000],
            )
            con.execute("INSERT INTO process_calls_process VALUES (?,?)", ["Caller.Multi", f"Multi.Child.{i}"])
            for j in range(4):
                leaf = f"Multi.Child.{i}.Grand.{j}"
                con.execute(
                    "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                    [leaf, body["prolog"], "", body["data"], "", "[]", "", 1000],
                )
                con.execute("INSERT INTO process_calls_process VALUES (?,?)", [f"Multi.Child.{i}", leaf])

        # 高扇入：300 个 caller，其中前 50 个自身还有一层上游（形成深度 3）
        for i in range(300):
            caller = f"FanIn.Caller.{i:03d}"
            con.execute(
                "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                [caller, "vC = 1;", "", _ti_block(12, seed=i), "", "[]", "", 400],
            )
            con.execute("INSERT INTO process_calls_process VALUES (?,?)", [caller, "Hub.Shared.Calc"])
            if i < 50:
                root = f"FanIn.Root.{i:03d}"
                con.execute(
                    "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                    [root, "vR = 1;", "", _ti_block(8, seed=i), "", "[]", "", 300],
                )
                con.execute("INSERT INTO process_calls_process VALUES (?,?)", [root, caller])

        # 循环调用：Cycle.A -> Cycle.B -> Cycle.A
        con.execute("INSERT INTO process_calls_process VALUES (?,?)", ["Cycle.A", "Cycle.B"])
        con.execute("INSERT INTO process_calls_process VALUES (?,?)", ["Cycle.B", "Cycle.A"])

        # 扇出放大：一个入口经 3 层、每层 30/30/3 展开，可达约 2700 个进程。
        # 用于验证「调用树按模型规模线性放大」的尾部风险，而非猜测。
        leaf = {"prolog": "vL = 1;", "data": _ti_block(10)}
        con.execute(
            "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
            ["Bomb.Root", "vR = 1;", "", _ti_block(20), "", "[]", "", 400],
        )
        for a in range(30):
            l1 = f"Bomb.L1.{a:02d}"
            con.execute(
                "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                [l1, leaf["prolog"], "", leaf["data"], "", "[]", "", 300],
            )
            con.execute("INSERT INTO process_calls_process VALUES (?,?)", ["Bomb.Root", l1])
            for b in range(30):
                l2 = f"Bomb.L2.{a:02d}.{b:02d}"
                con.execute(
                    "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                    [l2, leaf["prolog"], "", leaf["data"], "", "[]", "", 300],
                )
                con.execute("INSERT INTO process_calls_process VALUES (?,?)", [l1, l2])
                for c in range(3):
                    l3 = f"Bomb.L3.{a:02d}.{b:02d}.{c}"
                    con.execute(
                        "INSERT INTO processes VALUES (?,?,?,?,?,?,?,?)",
                        [l3, leaf["prolog"], "", leaf["data"], "", "[]", "", 300],
                    )
                    con.execute("INSERT INTO process_calls_process VALUES (?,?)", [l2, l3])
    finally:
        con.close()
    return {
        "normal": "Normal.LoadSales",
        "long": "Long.Reconciliation.Deep",
        "multi_call": "Caller.Multi",
        "high_fan_in": "Hub.Shared.Calc",
        "loop": "Loop.While.Write",
        "long_name": LONG_NAME,
        "cycle": "Cycle.A",
        "fan_out_bomb": "Bomb.Root",
    }


# ---------------------------------------------------------------------------
# 连接包装：统计 SQL 次数与查询耗时
# ---------------------------------------------------------------------------

class CountingCon:
    """最小包装，只拦截 execute，统计次数与累计耗时。"""

    def __init__(self, con, stats: dict):
        self._con = con
        self._stats = stats

    def execute(self, sql, params=None):
        t0 = time.perf_counter()
        try:
            return self._con.execute(sql, params) if params is not None else self._con.execute(sql)
        finally:
            cost = (time.perf_counter() - t0) * 1000.0
            self._stats["sql_count"] += 1
            self._stats["sql_ms"] += cost
            if self._stats.get("record"):
                self._stats["sql_calls"].append({"sql": " ".join(str(sql).split())[:160],
                                                 "params": str(params)[:80] if params else "",
                                                 "ms": round(cost, 3)})

    def close(self):
        self._con.close()

    def __getattr__(self, item):
        return getattr(self._con, item)


# ---------------------------------------------------------------------------
# 模板渲染：用真实 Jinja 环境与真实模板，避免自造近似
# ---------------------------------------------------------------------------

def _fake_request():
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/explorer/process/x",
             "headers": [], "query_string": b"", "scheme": "http",
             "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 1),
             "root_path": "", "http_version": "1.1"}
    return Request(scope)


def render_page(proc, call_tree, *, include_call_tree=True) -> str:
    """渲染 process_view.html。call_tree=None 时模拟「调用树未加载」的惰性形态。"""
    from tm1_insight.api.app import templates
    env = templates.env
    saved = {k: env.globals.get(k) for k in ("current_data_source", "model_fingerprint", "research_model")}
    env.globals["current_data_source"] = lambda: {"type": "demo", "label": "demo", "ready": True,
                                                  "location": "", "counts": {}, "db_path": "",
                                                  "db_size": 0, "has_data": True, "error": None}
    env.globals["model_fingerprint"] = lambda: "synthetic"
    env.globals["research_model"] = lambda: "synthetic"
    try:
        return env.get_template("process_view.html").render(
            request=_fake_request(), proc=proc, call_tree=call_tree,
            search_source="synthetic", include_call_tree=include_call_tree,
        )
    finally:
        for k, v in saved.items():
            if v is None:
                env.globals.pop(k, None)
            else:
                env.globals[k] = v


def projected_dom_nodes(total_lines: int, code_chars: int, *, line_cap: int = 10_000,
                        char_cap: int = 1_000_000) -> dict:
    """由服务端数据推算高亮后的 DOM 规模（推导值，非浏览器实测）。

    syntax.js 的 render() 每行固定生成 div.code-line > span.lineno + span.line-code，
    故元素数下限 = 行数 × 3；超出行数/字符上限时走纯文本降级，退化为 1 个 <pre>。
    """
    if code_chars > char_cap or total_lines > line_cap:
        return {"mode": "plain-text-fallback", "projected_elements": 1}
    return {"mode": "highlighted", "projected_elements": total_lines * 3}


# ---------------------------------------------------------------------------
# 单样本测量
# ---------------------------------------------------------------------------

def measure_one(db_path: Path, name: str, iterations: int, *, lazy_tree: bool = True,
                warmup: int = 3) -> dict:
    """冷/热两态测量。

    冷 = 每次新建连接（含 DuckDB 打开成本）；热 = 复用同一连接。
    两种状态都先跑 warmup 次并丢弃，避免把「进程/扩展首次加载」算进稳态。
    """
    cold_total, warm_total = [], []
    sample = {}
    for mode, bucket in (("cold", cold_total), ("warm", warm_total)):
        shared = duckdb.connect(str(db_path), read_only=True) if mode == "warm" else None
        for i in range(iterations + warmup):
            stats = {"sql_count": 0, "sql_ms": 0.0, "sql_calls": [], "record": i == 0}
            t_conn0 = time.perf_counter()
            con = duckdb.connect(str(db_path), read_only=True) if shared is None else shared
            t_conn = (time.perf_counter() - t_conn0) * 1000.0
            counting = CountingCon(con, stats)
            try:
                t0 = time.perf_counter()
                proc = queries.get_process(counting, name)
                t_get = (time.perf_counter() - t0) * 1000.0
                t0 = time.perf_counter()
                tree = queries.process_call_tree(counting, name)
                t_tree = (time.perf_counter() - t0) * 1000.0
                t0 = time.perf_counter()
                html = render_page(proc, None if lazy_tree else tree)
                t_render = (time.perf_counter() - t0) * 1000.0
            finally:
                if shared is None:
                    con.close()
            if i < warmup:
                continue
            total = t_conn + t_get + t_tree + t_render
            bucket.append(total)
            sample = {
                "connect_ms": round(t_conn, 2),
                "get_process_ms": round(t_get, 2),
                "call_tree_ms": round(t_tree, 2),
                "render_ms": round(t_render, 2),
                "sql_count": stats["sql_count"],
                "sql_ms": round(stats["sql_ms"], 2),
                "sql_calls": stats["sql_calls"],
                "html_bytes": len(html.encode("utf-8")),
                "total_lines": proc["total_lines"],
                "section_lines": proc["section_lines"],
                "call_tree_callers": len(tree["callers"]),
                "call_tree_callees": len(tree["callees"]),
                "tree_nodes": _count_nodes(tree),
            }
        if shared is not None:
            shared.close()
    sample["cold_p50_ms"] = round(statistics.median(cold_total), 2)
    sample["cold_p95_ms"] = round(_p95(cold_total), 2)
    sample["warm_p50_ms"] = round(statistics.median(warm_total), 2)
    sample["warm_p95_ms"] = round(_p95(warm_total), 2)
    sample["iterations"] = iterations
    return sample


def _count_nodes(node) -> int:
    total = 1
    for key in ("callers", "callees", "children"):
        for child in node.get(key) or []:
            total += _count_nodes(child)
    return total


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def _machine() -> dict:
    import os
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "processor": platform.processor() or "n/a",
        "duckdb": duckdb.__version__,
    }


# ---------------------------------------------------------------------------
# live：只读当前数据源
# ---------------------------------------------------------------------------

def pick_live_samples(db_path: Path) -> tuple[list[tuple[str, str]], dict]:
    """只读挑选代表性样本（角色, 名称）。名称只在内存中流转，不写入产物。"""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT name, code_length FROM processes WHERE code_length IS NOT NULL ORDER BY code_length DESC"
        ).fetchall()
        fanin = dict(con.execute(
            "SELECT callee, count(*) FROM process_calls_process GROUP BY 1"
        ).fetchall())
        fanout = dict(con.execute(
            "SELECT caller, count(*) FROM process_calls_process GROUP BY 1"
        ).fetchall())
        scale = {"processes": con.execute("SELECT count(*) FROM processes").fetchone()[0],
                 "cubes": con.execute("SELECT count(*) FROM cubes").fetchone()[0],
                 "call_edges": con.execute("SELECT count(*) FROM process_calls_process").fetchone()[0]}
    finally:
        con.close()
    if not rows:
        return [], scale
    picked: list[tuple[str, str]] = [("largest", rows[0][0])]
    if fanin:
        hub = max(fanin, key=fanin.get)
        if hub != picked[0][1]:
            picked.append(("highest_fan_in", hub))
    if fanout:
        spread = max(fanout, key=fanout.get)
        if all(spread != n for _, n in picked):
            picked.append(("highest_fan_out", spread))
    picked.append(("median_size", rows[len(rows) // 2][0]))
    picked.append(("small", rows[-1][0]))
    return picked, scale


def measure_live(processes: list[tuple[str, str]], iterations: int) -> dict:
    """只读当前数据源。结果键用角色名，避免在产物里出现真实对象名。"""
    from tm1_insight.config import get_settings
    db_path = get_settings().db_path
    out = {"db": "<read-only>", "samples": {}}
    for role, name in processes:
        out["samples"][role] = measure_one(Path(db_path), name, iterations)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["synthetic", "live"], default="synthetic")
    ap.add_argument("--iterations", type=int, default=12)
    ap.add_argument("--process", action="append", default=None,
                    help="live 模式：role=名称；省略则自动挑选代表性样本")
    ap.add_argument("--out", default="")
    ap.add_argument("--eager-tree", action="store_true", help="连同调用树一起渲染（旧行为）")
    args = ap.parse_args()

    lazy_tree = not args.eager_tree
    report = {"machine": _machine(), "lazy_tree": lazy_tree}
    temps = []
    try:
        if args.model == "synthetic":
            folder = tempfile.mkdtemp(prefix="tm1-measure-")
            temps.append(folder)
            db_path = Path(folder) / "synthetic.duckdb"
            roles = build_synthetic(db_path)
            report["model"] = "synthetic"
            report["roles"] = roles
            report["samples"] = {}
            for role, name in roles.items():
                report["samples"][role] = measure_one(db_path, name, args.iterations, lazy_tree=lazy_tree)
        else:
            from tm1_insight.config import get_settings
            db_path = get_settings().db_path
            if args.process:
                samples = []
                for spec in args.process:
                    role, _, name = spec.partition("=")
                    samples.append((role or "sample", name or role))
                scale = {}
            else:
                samples, scale = pick_live_samples(Path(db_path))
            report["model"] = "live"
            report["scale"] = scale
            report.update(measure_live(samples, args.iterations))
    finally:
        import shutil
        for folder in temps:
            shutil.rmtree(folder, ignore_errors=True)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
