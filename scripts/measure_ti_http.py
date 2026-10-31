"""Stage 0 — /explorer/process/{name} 端到端 HTTP 耗时分解（进程内 ASGI，只读）。

只测量当前数据源，不写库、不联网、不启动外部端口。
输出：TTFB、完整响应耗时、响应体积、请求内 SQL 次数与耗时、各阶段占比。

用法：
  python scripts/measure_ti_http.py --iterations 10 --out before_http.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import importlib  # noqa: E402

app_module = importlib.import_module("tm1_insight.api.app")


class _TimerMiddleware:
    """记录请求内 SQL 次数/耗时与数据源探测耗时，不改业务逻辑。"""


def _p95(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def measure(client, url: str, iterations: int, warmup: int = 2) -> dict:
    times, sizes, sql_counts, sql_ms = [], [], [], []
    status = None
    for i in range(iterations + warmup):
        con = {"count": 0, "ms": 0.0}
        original_connect = app_module._store

        def patched_store():
            store = original_connect()
            real_connect = store.connect

            def counting_connect(*a, **k):
                conn = real_connect(*a, **k)
                return _Wrap(conn, con)

            store.connect = counting_connect
            return store

        app_module._store = patched_store
        try:
            t0 = time.perf_counter()
            resp = client.get(url)
            cost = (time.perf_counter() - t0) * 1000.0
        finally:
            app_module._store = original_connect
        status = resp.status_code
        if i < warmup:
            continue
        times.append(cost)
        sizes.append(len(resp.content))
        sql_counts.append(con["count"])
        sql_ms.append(con["ms"])
    return {
        "status": status,
        "p50_ms": round(statistics.median(times), 2),
        "p95_ms": round(_p95(times), 2),
        "min_ms": round(min(times), 2),
        "max_ms": round(max(times), 2),
        "body_kb": round(sizes[-1] / 1024.0, 1),
        "sql_p50": int(statistics.median(sql_counts)),
        "sql_ms_p50": round(statistics.median(sql_ms), 2),
        "iterations": iterations,
    }


class _Wrap:
    def __init__(self, con, stats):
        self._con = con
        self._stats = stats

    def execute(self, sql, params=None):
        t0 = time.perf_counter()
        try:
            return self._con.execute(sql, params) if params is not None else self._con.execute(sql)
        finally:
            self._stats["count"] += 1
            self._stats["ms"] += (time.perf_counter() - t0) * 1000.0

    def close(self):
        self._con.close()

    def __getattr__(self, item):
        return getattr(self._con, item)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--out", default="")
    ap.add_argument("--baseline", action="store_true",
                    help="对照基线：先单独测量 detect_current_source 与连接成本")
    args = ap.parse_args()

    from tm1_insight.datasource import detect_current_source
    from tm1_insight.config import get_settings

    extra = {}
    if args.baseline:
        t = []
        for _ in range(12):
            t0 = time.perf_counter()
            detect_current_source()
            t.append((time.perf_counter() - t0) * 1000.0)
        extra["detect_current_source_p50_ms"] = round(statistics.median(t), 2)

        from tm1_insight.store.db import Store
        t = []
        for _ in range(12):
            t0 = time.perf_counter()
            con = Store(get_settings()).connect(read_only=True)
            con.close()
            t.append((time.perf_counter() - t0) * 1000.0)
        extra["connect_p50_ms"] = round(statistics.median(t), 2)

        from tm1_insight.api.app import _process_search_source
        t = []
        for _ in range(12):
            t0 = time.perf_counter()
            _process_search_source()
            t.append((time.perf_counter() - t0) * 1000.0)
        extra["fingerprint_p50_ms"] = round(statistics.median(t), 2)

    client = TestClient(app_module.app)
    samples, _ = _pick(client)
    report = {"samples": {}, **extra}
    for role, url in samples:
        report["samples"][role] = measure(client, url, args.iterations)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


def _pick(client):
    """按对象规模挑选样本，只输出角色名。"""
    import duckdb
    from tm1_insight.config import get_settings
    con = duckdb.connect(str(get_settings().db_path), read_only=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM processes WHERE code_length IS NOT NULL ORDER BY code_length DESC LIMIT 1"
        ).fetchall()]
        median = con.execute(
            "SELECT name FROM processes WHERE code_length IS NOT NULL "
            "ORDER BY code_length LIMIT 1 OFFSET (SELECT count(*)//2 FROM processes)"
        ).fetchone()
        hub = con.execute(
            "SELECT callee FROM process_calls_process GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    picked = [("largest", names[0])]
    if median:
        picked.append(("median_size", median[0]))
    if hub:
        picked.append(("highest_fan_in", hub[0]))
    import urllib.parse
    return [(role, "/explorer/process/" + urllib.parse.quote(n)) for role, n in picked], None


if __name__ == "__main__":
    raise SystemExit(main())
