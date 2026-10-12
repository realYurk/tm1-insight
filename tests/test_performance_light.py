"""Task 19 性能测试（轻量）。

验证 Impact / Compare / Change Intelligence 不会出现明显无限等待，
并确认 Change Intelligence 的邻接表复用优化（不再对每个对象重建图）。

铁律：不触碰真实 data/。用内存数据构造。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tm1_insight.domain.model import Dependency, DependencyKind  # noqa: E402
from tm1_insight.lineage import get_upstream  # noqa: E402
from tm1_insight.change_intelligence import analyze_changes  # noqa: E402
from tm1_insight.impact import analyze_impact  # noqa: E402


def _make_chain(n: int) -> list[Dependency]:
    """构造 A0 -> A1 -> ... -> An 的依赖链（process writes cube）。"""
    deps = []
    for i in range(n):
        deps.append(Dependency(
            kind=DependencyKind.PROCESS_WRITES_CUBE,
            source=f"P{i}", target=f"C{i}",
        ))
    return deps


def test_impact_fast_on_chain():
    """Impact 分析在链式依赖上应快速完成（无无限等待）。"""
    deps = _make_chain(200)
    t0 = time.time()
    result = analyze_impact(deps, "P0")
    elapsed = time.time() - t0
    # 200 个对象链式影响应远小于 2 秒
    assert elapsed < 2.0, f"impact 分析耗时 {elapsed:.2f}s，疑似性能问题"
    assert len(result) > 0


def test_change_intelligence_terminates():
    """Change Intelligence 在多个 changed object 上应终止并返回结果。"""
    deps = _make_chain(100)
    before = {"processes": [], "rules": [], "cubes": [], "dimensions": []}
    after = {
        "processes": [],
        "rules": [],
        "cubes": [{"name": f"C{i}", "dimensions": [], "rules": []} for i in range(100)],
        "dimensions": [],
    }
    t0 = time.time()
    result = analyze_changes(before, after, deps)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"change intelligence 耗时 {elapsed:.2f}s，疑似性能问题"
    assert result.statistics["changed_count"] > 0


def test_get_upstream_adjacency_reuse():
    """验证 get_upstream 支持预构建邻接表（批量复用不改变结果）。"""
    deps = _make_chain(20)
    # 用默认方式（每次内部建图）
    r1 = get_upstream(deps, "C19")
    # 用预构建邻接表（复用）
    from tm1_insight.lineage.engine import build_adjacency
    adj = build_adjacency(deps)
    r2 = get_upstream(deps, "C19", _adj=adj)
    # 结果应一致（确定性）
    assert [l.target for l in r1] == [l.target for l in r2]
    assert [l.source for l in r1] == [l.source for l in r2]


def test_converging_graph_expands_each_node_once():
    """A layered DAG has exponentially many paths but only linearly many nodes."""
    from tm1_insight.lineage import get_downstream
    from tm1_insight.lineage.engine import build_adjacency

    deps = []
    previous = ["Start"]
    for level in range(24):
        current = [f"L{level:02}_{suffix}" for suffix in ("a", "b")]
        for source in previous:
            for target in current:
                deps.append(Dependency(kind=DependencyKind.PROCESS_CALLS_PROCESS,
                                       source=source, target=target))
        previous = current

    class CountingAdjacency(dict):
        expansions = 0

        def get(self, key, default=None):
            self.expansions += 1
            assert self.expansions <= 49, "A previously visited node was expanded again"
            return super().get(key, default)

    adjacency = CountingAdjacency(build_adjacency(deps))
    results = get_downstream(deps, "Start", _adj=adjacency)
    assert len(results) == 48
    last = next(item for item in results if item.target == "L23_b")
    assert last.depth == 24
    assert last.path == ("Start", *(f"L{level:02}_a" for level in range(23)), "L23_b")
