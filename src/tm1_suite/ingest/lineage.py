"""深血缘后处理（迁移自 tm1tree/postprocess_lineage.py）。

把 hard_extract.process_ti 的输出过滤日志、聚合为业务血缘结构，
供 loader 写入 lineage 层（ti_summary/ti_flows/ti_flow_dims/...）。
"""
from __future__ import annotations

import re
from collections import defaultdict

from tm1_suite.ingest.hard_extract import process_ti

LOG_CUBE_PATTERNS = [
    "}APQProcessExecutionLog",
    "}APQCubeLastUpdatedbyProcess",
    "}APQ Process Response Message",
    "}Sys Process Execution Log",
    "Sys Process Execution Log",
    "}APQ Dimension Subsets",
]

LOG_MEASURE_VALUES = {
    "nProcessStartTime", "nProcessFinishTime", "nProcessStartedFlag",
    "nProcessCompletedFlag", "nProcessExecutionIndex",
    "nProcessExecutionIntraDayIndex", "nMetaDataRecordCount",
    "nDataRecordCount", "nPrologMinorErrorCount", "nMetaDataMinorErrorCount",
    "nDataMinorErrorCount", "nProcessReturnCode", "sProcessErrorLogFile",
    "sRunBy", "sParams", "nLastTimeUpdate", "sProcess", "sProcessRunBy",
    "Start Time", "Finish Time", "Parameters", "Status",
    "Success Message", "Failure Message", "TM1ProcessError File",
    "Source",
}


def is_log_write(wp):
    target = wp.get("target_cube") or ""
    target_expr = wp.get("target_cube_expr") or ""
    for pat in LOG_CUBE_PATTERNS:
        if pat in target or pat in target_expr:
            return True
    if target_expr in ("sProcLogCube", "sCubLogCube", "cCubRespMsg"):
        return True
    dim_args = wp.get("dim_args") or []
    if dim_args:
        last_val = dim_args[-1].get("value", "")
        last_expr = dim_args[-1].get("expr", "")
        if last_val in LOG_MEASURE_VALUES:
            return True
        if last_expr and last_expr.strip("'\"") in LOG_MEASURE_VALUES:
            return True
    return False


def is_log_read(rp):
    source = rp.get("source_cube") or ""
    for pat in LOG_CUBE_PATTERNS:
        if pat in source:
            return True
    return False


def is_framework_read(rp):
    """框架/系统 cube 读取：} 花括号开头的都是 TM1 系统对象，对业务血缘无意义。"""
    source = rp.get("source_cube") or ""
    if source.startswith("}"):
        return True
    return source == "}APQ Settings"


def extract_source_cubes_from_dims(write_points):
    """从 dim_args 里提取嵌套 CellGet 引用的源 Cube"""
    cubes = set()
    for wp in write_points:
        for d in wp.get("dim_args", []):
            val = d.get("value", "")
            m = re.match(r'←([^\[]+)\[', val)
            if m:
                cube = m.group(1).strip()
                if cube and not cube.startswith("<"):
                    cubes.add(cube)
    return cubes


def extract_data_flows(ti):
    business_writes = [wp for wp in ti["write_points"] if not is_log_write(wp)]
    business_reads = [rp for rp in ti["read_points"]
                      if not is_log_read(rp) and not is_framework_read(rp)]

    writes_by_cube = defaultdict(list)
    for wp in business_writes:
        cube = wp["target_cube"]
        if not cube or cube.startswith("<"):
            continue
        writes_by_cube[cube].append(wp)

    reads_by_cube = defaultdict(list)
    for rp in business_reads:
        cube = rp["source_cube"]
        if not cube or cube.startswith("<"):
            continue
        reads_by_cube[cube].append(rp)

    nested_sources = extract_source_cubes_from_dims(business_writes)
    for c in nested_sources:
        if c not in reads_by_cube:
            reads_by_cube[c] = []

    flows = []
    for target_cube, target_wps in writes_by_cube.items():
        dim_combos = []
        seen = set()
        for wp_idx, wp in enumerate(target_wps):
            dims = tuple(d.get("value", "?") for d in wp["dim_args"])
            if dims not in seen:
                seen.add(dims)
                dim_combos.append({
                    "write_point_index": wp_idx,
                    "operation": wp["operation"],
                    "line": wp.get("line"),
                    "conditions": wp.get("conditions", []),
                    "dimensions": [
                        {"expr": d.get("expr"), "value": d.get("value")}
                        for d in wp["dim_args"]
                    ],
                })

        flows.append({
            "target_cube": target_cube,
            "source_cubes": list(reads_by_cube.keys()),
            "write_points": dim_combos,
        })

    return {
        "business_writes_by_cube": dict(writes_by_cube),
        "business_reads_by_cube": dict(reads_by_cube),
        "flows": flows,
    }


def summarize_bedrock(callee):
    mapping = {
        "}bedrock.cube.data.clear": "清空目标 Cube",
        "}bedrock.cube.data.copy": "复制数据",
        "}bedrock.cube.data.zeroout": "清零",
        "}bedrock.cube.view.create": "创建视图",
        "}bedrock.cube.viewandsubsets.delete": "清理视图和子集",
        "}bedrock.hier.sub.create.bymdx": "按 MDX 创建子集",
        "}bedrock.hier.sub.delete": "删除子集",
    }
    return mapping.get(callee, "框架调用")


def process_one(ti):
    flows = extract_data_flows(ti)
    return {
        "name": ti["name"],
        "params": ti["params"],
        "source_cubes": list(flows["business_reads_by_cube"].keys()),
        "target_cubes": list(flows["business_writes_by_cube"].keys()),
        "flows": flows["flows"],
        "business_calls": [
            c for c in ti["calls"]
            if c["callee"] and not c["callee"].startswith("}bedrock.")
               and not c["callee"].startswith("}APQ.")
               and c["callee"] != "<sProc>"
        ],
        "framework_calls": [
            {"callee": c["callee"], "purpose": summarize_bedrock(c["callee"])}
            for c in ti["calls"]
            if c["callee"] and c["callee"].startswith("}bedrock.")
        ],
    }


def analyze_ti(ti_json: dict) -> dict:
    """入口：输入一个 TI 的 dict（raw JSON），输出精简血缘结构。"""
    return process_one(process_ti(ti_json))


def _safe_analyze(ti_json: dict) -> tuple[str, object]:
    """多进程安全的入口：异常不抛出，返回 (status, payload)。

    status == "ok" 时 payload 为 analyze_ti 的结果；"err" 时为错误信息字符串。
    供 loader 用 ProcessPoolExecutor 并行调用。
    """
    try:
        return ("ok", analyze_ti(ti_json))
    except Exception as e:  # noqa: BLE001
        return ("err", f"{ti_json.get('name', '?')}: {e}")
