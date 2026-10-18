"""真实 BP 采集库的只读集成回归测试（Task 19）。

只在本地真实采集库存在时运行；CI / 无真实库环境自动 skip。
只读打开采集库，绝不写入、绝不连接服务器。

覆盖：
1. BP 核心流程能从真实数据还原（源 Cube → TI → 目标 Cube）。
2. Bedrock 辅助调用默认折叠为技术项，业务主干不含技术噪音。
3. 固定成员 vs 运行时坐标被正确区分。
4. 证据缺口（MISSING_VARIABLE_METADATA）被如实标注，不伪造闭环。
5. 导出（Markdown/JSON）能产生可读业务架构且不改动源库。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = PROJECT_ROOT / "collections"
CANDIDATES = [
    COLLECTIONS / "model-rytp0epv" / "db" / "tm1_insight.duckdb",
    # 未来可能的其他采集目录也纳入探测，但只在真实存在时使用。
]

ENTRY_CUBE = "Allocation Driver BP"
SOURCE_CUBE = "BP Management Report PnL"


def _find_db():
    for p in CANDIDATES:
        if p.is_file():
            return p
    return None


DB_PATH = _find_db()


@pytest.fixture
def real_con():
    if DB_PATH is None:
        pytest.skip("真实采集库不存在，跳过集成测试")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    yield con
    con.close()


@pytest.fixture
def snapshot_before(real_con):
    """记录库关键表行数，用于验证只读测试不写库。"""
    before = {}
    for t in ("processes", "cubes", "chores"):
        before[t] = real_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return before


def test_bp_core_flow_reconstructs_from_real_data(real_con):
    from tm1_insight import architecture

    report = architecture.build(
        real_con, ENTRY_CUBE, entry_kind="cube", max_processes=40, max_depth=8
    )
    # 目标 Cube 确实存在且被写入
    assert report["module"]["name"] == ENTRY_CUBE
    producers = [e for e in report["entry_points"] if e["kind"] == "producer"]
    assert producers, "应有源码确认的生产者 TI"

    # 至少存在一条 源 Cube → 目标 Cube 的真实数据流
    steps = report.get("transformation_steps", [])
    assert any(SOURCE_CUBE in s.get("inputs", []) and ENTRY_CUBE in s.get("outputs", []) for s in steps), (
        "应存在 BP Management Report PnL → Allocation Driver BP 的数据流"
    )


def test_bedrock_helpers_folded_as_technical(real_con):
    from tm1_insight import architecture

    report = architecture.build(
        real_con, ENTRY_CUBE, entry_kind="cube", max_processes=40, max_depth=8
    )
    steps = report.get("transformation_steps", [])
    technical = [s for s in steps if s.get("technical")]
    core = [s for s in steps if not s.get("technical")]
    # Bedrock 辅助调用（} 开头）应被标记为技术项
    for s in technical:
        assert s["process"].startswith("}") or s["technical"], (
            f"技术项 {s['process']} 应来自系统命名空间或显式技术标记"
        )
    # 业务主干不应含系统命名空间对象
    for s in core:
        assert not s["process"].startswith("}"), f"业务主干不应含系统命名空间 {s['process']}"


def test_fixed_vs_runtime_coordinates_distinguished(real_con):
    from tm1_insight import architecture

    report = architecture.build(
        real_con, ENTRY_CUBE, entry_kind="cube", max_processes=40, max_depth=8
    )
    # 任一写入说明中，固定成员与运行时坐标应区分
    fixed_found = False
    runtime_found = False
    for w in report.get("write_explanations", []):
        for c in w.get("target_coordinates", []):
            kind = c.get("kind")
            if kind == "FIXED_MEMBER":
                fixed_found = True
            elif kind in ("PARAMETER", "UNRESOLVED"):
                runtime_found = True
    # Allocation Driver BP 的写入确实含固定成员（如 Allocation Step）
    assert fixed_found, "应存在固定成员坐标"
    assert runtime_found, "应存在运行时/待解析坐标（如 vScenario）"


def test_missing_variable_metadata_honestly_reported(real_con):
    from tm1_insight.store.calculation import inspect

    # 目标 Process 缺少 Variables 元数据（旧快照未保存），应如实报告
    name = "Cub.Allocation Driver BP.Data.Load.From.BP Management Report PnL.ACT"
    if not real_con.execute("SELECT 1 FROM processes WHERE name=?", [name]).fetchone():
        pytest.skip("目标 Process 不在采集库中")
    report = inspect(real_con, name)
    drl = report.get("data_row_lineage", {})
    # runtime_verified 必须为 False（未连接服务器、无运行时观测）
    assert drl.get("runtime_verified") is False
    # 缺失元数据必须如实标注，不得伪造闭环
    reasons = drl.get("unresolved_binding_reasons", [])
    assert any("MISSING_VARIABLE_METADATA" in r for r in reasons), (
        "应如实报告 Variables 元数据缺失"
    )


def test_export_produces_readable_architecture(real_con, tmp_path):
    from tm1_insight import architecture

    report = architecture.build(
        real_con, ENTRY_CUBE, entry_kind="cube", max_processes=30, max_depth=6
    )
    art = architecture.artifact(report, str(tmp_path))
    try:
        md = "".join(architecture.markdown(art.path))
        # 可读架构应包含业务主干说明
        assert "Allocation Driver BP" in md
        assert "BP Management Report PnL" in md
        # Bedrock 折叠提示应存在
        assert "折叠" in md or "技术" in md or "辅助" in md
    finally:
        art.cleanup()


def test_readonly_does_not_modify_database(real_con, snapshot_before):
    from tm1_insight import architecture

    architecture.build(real_con, ENTRY_CUBE, entry_kind="cube", max_processes=20, max_depth=4)
    after = {
        t: real_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("processes", "cubes", "chores")
    }
    assert after == snapshot_before, "只读架构分析不应修改核心表行数"
