"""真实大模型关系查询性能验收（只读，离线）。

记录：查询类型、冷/热、返回节点与关系数、截断状态、Rule 分析范围、
      以及索引构建耗时（一次性 O(对象+索引行)，不传浏览器）。
用法：TM1_BASE=http://127.0.0.1:8011 python scripts/perf_workbench.py [cold|warm]
"""
import json
import os
import statistics
import sys
import time
import urllib.request

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
MODE = sys.argv[1] if len(sys.argv) > 1 else "warm"
# 合成示例名；真实模型请用 TM1_PERF_CUBES / TM1_PERF_TI 覆盖。
CUBES = os.environ.get("TM1_PERF_CUBES", "Sales Cost Driver,Planning PnL,Cost Calculation,Product Master,Sys Planning Cube").split(",")
ACT = os.environ.get("TM1_PERF_TI", "Cub.Sales Cost Driver.Data.Load.From.Planning PnL.ACT")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    start = time.perf_counter()
    with OPENER.open(req, timeout=300) as resp:
        payload = json.load(resp)
    return payload, (time.perf_counter() - start) * 1000


def run(label, body, repeat=3):
    samples, last = [], None
    for _ in range(repeat):
        last, ms = api("/api/workbench/graph", body)
        samples.append(ms)
    limits = last["limits"]
    scope = last.get("rule_scope") or {}
    print("| %s | %s | %.0f | %.0f | %d | %d | %d | %d | %s | %s |" % (
        label, MODE,
        statistics.median(samples), min(samples),
        len(last["nodes"]), len(last["edges"]),
        limits.get("prefix_matches", 0), len(limits.get("missing", [])),
        "是" if limits.get("truncated") else "否",
        "%d/%d" % (scope.get("owners_analyzed", 0), scope.get("owners_considered", 0)) if scope else "-",
    ))
    return last


def main():
    snap = api("/api/workbench/objects?q=&type=cube")[0]["snapshot_id"]
    print("snapshot:", snap[:16], "mode:", MODE)
    # 索引构建（进程级缓存）：一次构建，全部查询复用。
    t0 = time.perf_counter()
    api("/api/workbench/graph", {"snapshot_id": snap, "objects": [{"type": "cube", "name": CUBES[0]}], "depth": 0})
    print("索引首查（含索引构建）: %.0f ms" % ((time.perf_counter() - t0) * 1000))
    print()
    print("| 查询 | 模式 | 中位(ms) | 最快(ms) | 节点 | 关系 | 前缀匹配 | 缺失 | 截断 | Rule分析/候选 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    run("单 Cube：Sales Cost Driver",
        {"snapshot_id": snap, "objects": [{"type": "cube", "name": CUBES[0]}], "depth": 2, "node_budget": 60})
    run("单 Cube："+CUBES[1],
        {"snapshot_id": snap, "objects": [{"type": "cube", "name": CUBES[1]}], "depth": 2, "node_budget": 60})
    run("前缀路径：SC* → BP*",
        {"snapshot_id": snap, "source_prefix": "SC*", "target_prefix": "BP*", "depth": 4, "node_budget": 60, "view": "cubes"})
    run("前缀路径：BP* → *（上游）",
        {"snapshot_id": snap, "source_prefix": "BP*", "depth": 3, "node_budget": 60, "direction": "downstream"})
    run("手动多 Cube（5 个）",
        {"snapshot_id": snap, "objects": [{"type": "cube", "name": n} for n in
         CUBES],
         "depth": 2, "node_budget": 80})
    run("单 TI：ACT 处理过程",
        {"snapshot_id": snap, "objects": [{"type": "process",
         "name": ACT}],
         "view": "objects", "depth": 1, "node_budget": 40})


if __name__ == "__main__":
    main()
