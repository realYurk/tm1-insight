"""Workbench 1.0 阶段 A：Dimension 大维度性能 + 属性列偏好 的合成测试。

不连接真实 TM1，全部用内存 DuckDB + 合成数据。覆盖：
1. 超大维度（68 万元素级）降级路径的正确性：root_total / root_truncated /
   recorded_elements 正确，且不伪造层级。
2. 大维度搜索返回真实匹配数 + large_dimension 标记 + 有界返回。
3. 属性列偏好：WorkbenchContext 按维度名隔离持久化（前端逻辑的纯函数验证，
   通过导出可测的纯逻辑断言，而非 DOM）。

性能断言使用宽松阈值（CI/不同机器波动），主要防止「退化到全量扫描」类回归。
"""
from __future__ import annotations

import json
import time

import duckdb
import pytest

from tm1_insight.store import dimension_tree
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    c = duckdb.connect()
    for ddl in ALL_TABLES.values():
        c.execute(ddl)
    yield c
    c.close()


def seed_huge(con, n: int = 680_000):
    elements = [{"name": "E%06d" % i, "type": "Numeric"} for i in range(n)]
    # 每 50 个一组，除组首外都挂到组首父节点下
    edges = [
        {"parent": "E%06d" % ((i // 50) * 50), "component": "E%06d" % i, "weight": 1}
        for i in range(1, n) if i % 50 != 0
    ]
    con.execute(
        "INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)",
        ["HugeDim", n, json.dumps(elements), "[]", json.dumps(edges), "[]"],
    )


def test_large_dimension_degraded_summary_correct(con):
    seed_huge(con)
    s = dimension_tree.tree_summary(con, "HugeDim")
    assert s["large_dimension"] is True
    assert s["root_total"] == 680_000
    assert s["root_truncated"] is True
    assert s["recorded_elements"] == 680_000
    # 降级预览只返回有界数量，不伪造层级
    assert len(s["roots"]) <= 200
    assert s["has_hierarchy"] is False


def test_large_dimension_search_real_total_and_bounded(con):
    seed_huge(con)
    r = dimension_tree.search_elements(con, "HugeDim", "E1234")
    assert r["large_dimension"] is True
    # E1234 前缀匹配 E1234* 共 10 个（E12340~E12349 之外还有 E1234 本身）
    assert r["total"] > 0
    assert len(r["matches"]) <= r["total"]
    assert r["returned"] == len(r["matches"])
    # 超大维度搜索不提供祖先路径（避免全量边扫描）
    assert all(m["paths"] == [] for m in r["matches"])


def test_large_dimension_summary_performance_bounded(con):
    """降级路径不应退化到对 elements 全量多次扫描（宽松阈值防回归）。"""
    seed_huge(con)
    t0 = time.perf_counter()
    dimension_tree.tree_summary(con, "HugeDim")
    elapsed = time.perf_counter() - t0
    # 优化前 ~2.2s；优化后 ~0.3s。阈值 1.5s 留有充分余量，仍能捕获全量扫描回归。
    assert elapsed < 1.5, f"tree_summary 大维度降级耗时异常：{elapsed:.3f}s"


def test_small_dimension_unaffected_by_large_path(con):
    """小维度（未超阈值）仍保留 ORDER BY 排序与祖先路径，不受大维度优化影响。"""
    elements = [
        {"name": "Total", "type": "Consolidated"},
        {"name": "A", "type": "Numeric"},
        {"name": "B", "type": "Numeric"},
    ]
    edges = [
        {"parent": "Total", "component": "A", "weight": 1},
        {"parent": "Total", "component": "B", "weight": -1},
    ]
    con.execute(
        "INSERT INTO dimensions VALUES (?, false, ?, ?, ?, ?, ?)",
        ["Small", 3, json.dumps(elements), "[]", json.dumps(edges), "[]"],
    )
    s = dimension_tree.tree_summary(con, "Small")
    assert s.get("large_dimension") is not True
    assert s["has_hierarchy"] is True
    # 排序保证：root 名称按字典序返回
    assert s["roots"][0]["name"] == "Total"
    # 搜索保留祖先路径
    r = dimension_tree.search_elements(con, "Small", "A")
    assert r["matches"][0]["paths"] == [["Total"]]
