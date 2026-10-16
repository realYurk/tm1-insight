"""入库：读取 raw JSON → 解析依赖 → 写入 DuckDB，并导出 Parquet 层。

阶段 1 采用正则解析（复用 tm1tree/sqlite.py 的 PATTERNS），
语句级解析器（hard_extract）在阶段 2 接入，填充 lineage 层。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import duckdb

from tm1_insight.config import Settings
from tm1_insight.ingest.progress import Progress
from tm1_insight.store.db import Store
from tm1_insight.store.schema import ALL_TABLES

logger = logging.getLogger(__name__)

# 依赖解析正则（阶段 1：graph 层）
PATTERNS: dict[str, list[str]] = {
    "reads_cube": [
        r"CellGetN\s*\(\s*'([^']+)'",
        r"CellGetS\s*\(\s*'([^']+)'",
        r"\bDB\s*\(\s*'([^']+)'",
    ],
    "writes_cube": [
        r"CellPutN\s*\([^,]+,\s*'([^']+)'",
        r"CellPutS\s*\([^,]+,\s*'([^']+)'",
        r"CellIncrementN\s*\([^,]+,\s*'([^']+)'",
    ],
    "calls_process": [
        r"ExecuteProcess\s*\(\s*'([^']+)'",
        r"RunProcess\s*\(\s*'([^']+)'",
    ],
    "maintains_dimension": [
        r"DimensionElementInsert\s*\(\s*'([^']+)'",
        r"DimensionElementComponentAdd\s*\(\s*'([^']+)'",
        r"DimensionElementDelete\s*\(\s*'([^']+)'",
    ],
    "updates_attribute": [
        r"AttrPutS\s*\([^,]+,\s*'([^']+)'",
        r"AttrPutN\s*\([^,]+,\s*'([^']+)'",
    ],
}


def _extract(text: str, patterns: list[str]) -> set[str]:
    results: set[str] = set()
    if not text:
        return results
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            results.add(m.group(1))
    return results


def _bulk(con: duckdb.DuckDBPyConnection, sql: str, rows: list[tuple]) -> None:
    """批量插入，空列表直接跳过（executemany 不接受空参数集）。"""
    if rows:
        con.executemany(sql, rows)


def _load_json_dir(base: Path, subdir: str) -> list[dict]:
    path = base / subdir
    if not path.is_dir():
        return []
    rows = []
    for fn in sorted(path.iterdir()):
        if not fn.suffix == ".json" or fn.name.startswith("_"):
            continue
        try:
            with open(fn, encoding="utf-8") as f:
                rows.append(json.load(f))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 %s 失败: %s", fn, e)
    return rows


class Loader:
    def __init__(self, settings: Settings, progress: Progress | None = None, strict: bool = False):
        self.settings = settings
        self.store = Store(settings)
        self.progress = progress
        self.strict = strict

    def _report(self, phase, done=None, total=None):
        if self.progress:
            self.progress(phase, done, total)

    def load(self, drop: bool = True) -> dict:
        raw = self.settings.raw_dir
        if not raw.is_dir():
            raise FileNotFoundError(f"raw 目录不存在: {raw}（请先运行 ingest 拉取）")

        t0 = time.time()
        self._report("load_raw")
        cubes = _load_json_dir(raw, "cubes")
        processes = _load_json_dir(raw, "processes")
        chores = _load_json_dir(raw, "chores")
        logger.info(
            "加载 JSON: cube=%d process=%d chore=%d (耗时 %.1fs)",
            len(cubes), len(processes), len(chores), time.time() - t0,
        )

        self.store.init_schema(drop=drop)
        con = self.store.connect()

        try:
            t0 = time.time()
            self._report("load_objects")
            self._insert_objects(con, cubes, processes, chores)
            self._stream_insert_dimensions(con, raw)
            logger.info("对象入库完成 (耗时 %.1fs)", time.time() - t0)

            t0 = time.time()
            self._report("relations")
            self._insert_relations(con, cubes, processes, chores)
            logger.info("关系解析完成 (耗时 %.1fs)", time.time() - t0)

            logger.info("开始血缘解析: %d 个 process（最慢的一步）", len(processes))
            t0 = time.time()
            self._insert_lineage(con, processes)
            logger.info("血缘解析完成 (耗时 %.1fs)", time.time() - t0)
        finally:
            con.close()

        stats = self.store.all_rows()
        logger.info("入库完成: %s", stats)

        self._export_parquet()
        return stats

    # ---- 对象表 ----
    def _insert_objects(self, con: duckdb.DuckDBPyConnection,
                        cubes, processes, chores) -> None:
        _bulk(
            con,
            "INSERT INTO cubes VALUES (?, ?, ?, ?, ?)",
            [
                (
                    c.get("name"),
                    json.dumps(c.get("dimensions", []) or [], ensure_ascii=False),
                    c.get("rules", "") or "",
                    bool(c.get("has_rules")),
                    len(c.get("dimensions", []) or []),
                )
                for c in cubes
            ],
        )
        _bulk(
            con,
            "INSERT INTO processes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    p.get("name"),
                    p.get("prolog", "") or "",
                    p.get("metadata", "") or "",
                    p.get("data", "") or "",
                    p.get("epilog", "") or "",
                    json.dumps(p.get("parameters", []) or [], ensure_ascii=False),
                    json.dumps(p.get("datasource"), ensure_ascii=False),
                    len("\n".join([
                        p.get("prolog", "") or "",
                        p.get("metadata", "") or "",
                        p.get("data", "") or "",
                        p.get("epilog", "") or "",
                    ])),
                )
                for p in processes
            ],
        )
        _bulk(
            con,
            "INSERT INTO chores VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    ch.get("name"),
                    json.dumps(ch.get("processes", []) or [], ensure_ascii=False),
                    len(ch.get("processes", []) or []),
                    ch.get("start_time") or "",
                    ch.get("frequency") or "",
                    ch.get("execution_mode") or "",
                    ch.get("active") or "",
                )
                for ch in chores
            ],
        )

    def _stream_insert_dimensions(self, con: duckdb.DuckDBPyConnection, raw: Path) -> int:
        """维度文件体积很大（近 1GB），流式分批入库，避免整批加载撑爆内存。"""
        path = raw / "dimensions"
        files = sorted(fn for fn in path.glob("*.json") if not fn.name.startswith("_"))
        self._report("load_dimensions", 0, len(files))
        if not path.is_dir():
            return 0
        batch: list[tuple] = []
        meta_batch: list[tuple] = []
        count = 0
        for index, fn in enumerate(files, 1):
            if not fn.suffix == ".json" or fn.name.startswith("_"):
                continue
            try:
                with open(fn, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as e:  # noqa: BLE001
                logger.warning("读取维度 %s 失败: %s", fn, e)
                if self.strict:
                    raise RuntimeError("Dimension input could not be read") from None
                continue
            batch.append((
                d.get("name"),
                bool(d.get("is_system", False)),
                d.get("element_count", 0),
                json.dumps(d.get("elements", []) or [], ensure_ascii=False),
                json.dumps(d.get("attributes", []) or [], ensure_ascii=False),
                json.dumps(d.get("edges", []) or [], ensure_ascii=False),
                json.dumps(d.get("subsets", []) or [], ensure_ascii=False),
            ))
            # 版本化扩展元数据：层级 / 子集定义 / 属性值（可选，无则留空）。
            # 独立表 dimension_metadata，不污染既有 dimensions 结构。
            if any(k in d for k in ("hierarchies", "subset_definitions", "attribute_values", "hierarchy_names")):
                meta_batch.append((
                    d.get("name"),
                    json.dumps(d.get("hierarchy_names", []) or [], ensure_ascii=False),
                    json.dumps(d.get("hierarchies", []) or [], ensure_ascii=False),
                    json.dumps(d.get("subset_definitions", []) or [], ensure_ascii=False),
                    json.dumps(d.get("attribute_values", {}) or {}, ensure_ascii=False),
                    d.get("collected_at"),
                ))
            count += 1
            self._report("load_dimensions", index, len(files))
            if len(batch) >= 500:
                _bulk(con, "INSERT INTO dimensions VALUES (?,?,?,?,?,?,?)", batch)
                if meta_batch:
                    _bulk(con, "INSERT INTO dimension_metadata VALUES (?,?,?,?,?,?)", meta_batch)
                batch = []
                meta_batch = []
        if batch:
            _bulk(con, "INSERT INTO dimensions VALUES (?,?,?,?,?,?,?)", batch)
        if meta_batch:
            _bulk(con, "INSERT INTO dimension_metadata VALUES (?,?,?,?,?,?)", meta_batch)
        logger.info("维度入库: %d 个（流式）", count)
        return count

    # ---- 关系表 ----
    def _insert_relations(self, con: duckdb.DuckDBPyConnection,
                          cubes, processes, chores) -> None:
        reads, writes, calls, dims_m, attrs_u = [], [], [], [], []
        # 语句级解析器：能识别变量形式的 cube 名（如 CellGetN(cCubSrc,...)），
        # 正则（PATTERNS）只匹配字面量 cube，会漏掉这类「数据源 cube 存变量里」的读取。
        from tm1_insight.ingest.hard_extract import (
            extract_assignments, extract_read_points, extract_write_points,
            extract_calls, extract_bedrock_filters, _bedrock_cube_points,
        )
        from tm1_insight.ingest.lineage import (
            is_log_read, is_framework_read, is_log_write,
        )

        all_cube_names = {c.get("name") for c in cubes}
        lowered_names = {n.lower(): n for n in all_cube_names}

        # 框架参数/控制 cube：每个 TI 都读，但对业务血缘是纯噪音
        FRAMEWORK_CUBES = {
            "}APQ Settings",
            "}APQProcessParametersInfo",
            "}APQProcessParallelizationControl",
            "}ClientGroups",
            "}CubeProperties",
            "}DimensionProperties",
            "}ClientProperties",
        }

        def _resolve_cube_name(val: str) -> str | None:
            """把解析出的名称规整到真实 cube 名（精确/大小写不敏感匹配）。"""
            if not val:
                return None
            if val in all_cube_names:
                return val
            if val.lower() in lowered_names:
                return lowered_names[val.lower()]
            return None

        def _datasource_cube(full: str, assignments: dict) -> str | None:
            """解析 TI 的数据源 cube（DatasourceNameForServer = <变量/字面量>）。

            数据源 cube 视图读取（DatasourceNameForServer = cCubSrc，cCubSrc='xxx'）
            不是 CellGetN/CellGetS 语句，语句级解析器抓不到，但它是真实的读取关系，
            必须纳入 process_reads_cube，否则「谁读我」这类下游血缘会漏掉这一大类 TI。
            """
            m = re.search(r"DatasourceNameForServer\s*=\s*([^;]+);", full, re.IGNORECASE)
            if not m:
                return None
            expr = m.group(1).strip()
            expr = re.sub(r"\s+#.*$", "", expr)
            if not expr:
                return None
            # 字面量直接规整；否则作为变量名追溯赋值链
            val = expr
            if not (expr.startswith("'") and expr.endswith("'")):
                from tm1_insight.ingest.hard_extract import resolve_value
                val = resolve_value(expr, assignments)
            if val and not val.startswith("<"):
                # resolve_value 对字符串字面量返回去引号的值
                return _resolve_cube_name(val.strip("'\""))
            return None

        def _stmt_reads_writes(full: str):
            """返回 (read_cubes, write_cubes)：正则 + 语句级解析 + 数据源声明的并集。

            语句级解析结果会过滤日志/框架 cube（}APQ Settings 等），
            避免业务血缘图被 3000+ 个 process 共读的框架参数 cube 淹没。
            """
            rd = _extract(full, PATTERNS["reads_cube"])
            wr = _extract(full, PATTERNS["writes_cube"])
            # 过滤框架 cube（每个 TI 都读的系统参数/控制 cube，业务血缘噪音）
            rd = {c for c in rd if c not in FRAMEWORK_CUBES}
            wr = {c for c in wr if c not in FRAMEWORK_CUBES}
            try:
                assignments = extract_assignments(full)
                for rp in extract_read_points(full, assignments):
                    c = rp.get("source_cube")
                    if not c or c.startswith("<"):
                        continue
                    if c in FRAMEWORK_CUBES or is_log_read(rp) or is_framework_read(rp):
                        continue
                    rd.add(c)
                for wp in extract_write_points(full, assignments):
                    c = wp.get("target_cube")
                    if not c or c.startswith("<"):
                        continue
                    if c in FRAMEWORK_CUBES or is_log_write(wp):
                        continue
                    wr.add(c)
                # 数据源 cube 视图读取（DatasourceNameForServer = cCubSrc）
                ds = _datasource_cube(full, assignments)
                if ds:
                    rd.add(ds)
                # bedrock 调用涉及的 cube（如 }bedrock.cube.data.copy 的 pCube）
                # 数据通过 bedrock 传递（无 CellPutN/CellGetN），需单独补进读写边
                calls = extract_calls(full, assignments)
                bedrock = extract_bedrock_filters(calls, full, assignments)
                b_writes, b_reads = _bedrock_cube_points(bedrock)
                for w in b_writes:
                    c = w.get("target_cube")
                    if c and not c.startswith("<") and c not in FRAMEWORK_CUBES:
                        wr.add(c)
                for r in b_reads:
                    c = r.get("source_cube")
                    if c and not c.startswith("<") and c not in FRAMEWORK_CUBES:
                        rd.add(c)
            except Exception:  # noqa: BLE001 —— 解析失败时退回正则结果
                pass
            return rd, wr

        for p in processes:
            name = p.get("name")
            full = "\n".join([
                p.get("prolog", "") or "",
                p.get("metadata", "") or "",
                p.get("data", "") or "",
                p.get("epilog", "") or "",
            ])
            rd, wr = _stmt_reads_writes(full)
            for cube in rd:
                reads.append((name, cube))
            for cube in wr:
                writes.append((name, cube))
            for callee in _extract(full, PATTERNS["calls_process"]):
                calls.append((name, callee))
            for dim in _extract(full, PATTERNS["maintains_dimension"]):
                dims_m.append((name, dim))
            for dim in _extract(full, PATTERNS["updates_attribute"]):
                attrs_u.append((name, dim))

        _bulk(con, "INSERT INTO process_reads_cube VALUES (?, ?)", reads)
        _bulk(con, "INSERT INTO process_writes_cube VALUES (?, ?)", writes)
        _bulk(con, "INSERT INTO process_calls_process VALUES (?, ?)", calls)
        _bulk(con, "INSERT INTO process_maintains_dimension VALUES (?, ?)", dims_m)
        _bulk(con, "INSERT INTO process_updates_attribute VALUES (?, ?)", attrs_u)

        cube_dim_rows = [
            (c.get("name"), d, i)
            for c in cubes
            for i, d in enumerate(c.get("dimensions", []) or [])
        ]
        _bulk(con, "INSERT INTO cube_has_dimension VALUES (?, ?, ?)", cube_dim_rows)

        all_cube_names = {c.get("name") for c in cubes}
        rule_refs = []
        for c in cubes:
            cube_name = c.get("name")
            for m in re.finditer(r"\bDB\s*\(\s*'([^']+)'", c.get("rules", "") or "", re.IGNORECASE):
                src = m.group(1)
                if src in all_cube_names:
                    rule_refs.append((cube_name, src))
        _bulk(con, "INSERT INTO rule_references_cube VALUES (?, ?)", rule_refs)

        chore_rows = []
        for ch in chores:
            for step in ch.get("processes", []) or []:
                if isinstance(step, dict):
                    pname = step.get("name")
                    order = step.get("step_order")
                    if pname:
                        chore_rows.append((ch.get("name"), pname, order))
        _bulk(con, "INSERT INTO chore_runs_process VALUES (?, ?, ?)", chore_rows)

    # ---- 血缘层（语句级解析） ----
    def _insert_lineage(self, con: duckdb.DuckDBPyConnection, processes) -> None:
        from concurrent.futures import ProcessPoolExecutor
        from tm1_insight.ingest.lineage import _safe_analyze

        summary_rows: list[tuple] = []
        flow_rows: list[tuple] = []
        flow_dim_rows: list[tuple] = []
        business_call_rows: list[tuple] = []
        framework_call_rows: list[tuple] = []

        total = len(processes)
        self._report("lineage", 0, total)
        workers = max(1, min(self.settings.tm1_max_workers, os.cpu_count() or 1))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            def batches():
                # Do not queue the entire model: cancellation waits for at most this batch.
                size = workers * 16
                for offset in range(0, total, size):
                    self._report("lineage", offset, total)
                    yield from pool.map(_safe_analyze, processes[offset:offset + size], chunksize=4)

            for idx, (status, payload) in enumerate(batches(), 1):
                self._report("lineage", idx, total)
                if status == "err":
                    logger.warning("解析失败: %s", payload)
                    if self.strict:
                        raise RuntimeError("Process analysis failed")
                    continue
                r = payload
                name = r["name"]
                summary_rows.append((
                    name,
                    json.dumps(r["params"], ensure_ascii=False),
                    len(r["source_cubes"]),
                    len(r["target_cubes"]),
                    len(r["business_calls"]),
                    bool(r["flows"]),
                ))
                for flow in r["flows"]:
                    flow_rows.append((
                        name,
                        flow["target_cube"],
                        json.dumps(flow["source_cubes"], ensure_ascii=False),
                        len(flow["write_points"]),
                    ))
                    for wp in flow["write_points"]:
                        wp_id = f"{name}::{flow['target_cube']}::{wp.get('write_point_index', 0)}"
                        conds_json = json.dumps(wp.get("conditions", []), ensure_ascii=False)
                        for i, d in enumerate(wp["dimensions"]):
                            flow_dim_rows.append((
                                name, flow["target_cube"], wp_id, wp["operation"],
                                i, d.get("expr"), d.get("value"), conds_json,
                            ))
                for c in r["business_calls"]:
                    business_call_rows.append((
                        name, c["callee"],
                        json.dumps(c.get("params") or {}, ensure_ascii=False),
                    ))
                for c in r["framework_calls"]:
                    framework_call_rows.append((name, c["callee"], c["purpose"]))

                if idx % 200 == 0 or idx == total:
                    logger.info("血缘解析 %d/%d", idx, total)

        _bulk(con, "INSERT INTO ti_summary VALUES (?,?,?,?,?,?)", summary_rows)
        _bulk(con, "INSERT INTO ti_flows VALUES (?,?,?,?)", flow_rows)
        _bulk(con, "INSERT INTO ti_flow_dims VALUES (?,?,?,?,?,?,?,?)", flow_dim_rows)
        _bulk(con, "INSERT INTO ti_business_calls VALUES (?,?,?)", business_call_rows)
        _bulk(con, "INSERT INTO ti_framework_calls VALUES (?,?,?)", framework_call_rows)

    # ---- Parquet 层 ----
    def _export_parquet(self) -> None:
        out_dir = self.settings.parquet_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        con = self.store.connect(read_only=True)
        try:
            self._report("parquet", 0, len(ALL_TABLES))
            for index, table in enumerate(ALL_TABLES, 1):
                con.execute(f"COPY {table} TO '{out_dir / (table + '.parquet')}' (FORMAT PARQUET)")
                self._report("parquet", index, len(ALL_TABLES))
        finally:
            con.close()
        logger.info("Parquet 已导出 → %s", out_dir)
