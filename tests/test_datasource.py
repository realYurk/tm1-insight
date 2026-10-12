"""Task 19 数据源管理测试。

覆盖：
- 数据源状态识别（无数据 → EMPTY / 有数据 → REAL_LOCAL / Demo → DEMO）
- Demo 数据加载（能 load、Dashboard 有数据、依赖可构建）
- 目录检测（成功 / 失败 / 非法路径 / 结构不完整）
- 数据源切换（demo / local / reset）

铁律：绝不触碰真实 data/。所有写入都走 tmp_path 隔离。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tm1_insight.datasource as ds  # noqa: E402
import tm1_insight.config as config  # noqa: E402
from tm1_insight.config import set_data_dir, get_settings  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """隔离：把用户数据根目录和 demo 目录都指向临时目录，绝不碰真实 data/。"""
    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    set_data_dir(None)
    get_settings.cache_clear()
    yield tmp_path


def _make_real_db(data_dir: Path) -> Path:
    """在 data_dir 下造一个最小「真实」DuckDB（含 cubes 数据）。"""
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "tm1_insight.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        from tm1_insight.store.schema import ALL_TABLES
        for name in ALL_TABLES:
            con.execute(f"DROP TABLE IF EXISTS {name}")
        for ddl in ALL_TABLES.values():
            con.execute(ddl)
        con.execute("INSERT INTO cubes VALUES ('TestCube', '[]', '', false, 0)")
        con.execute("INSERT INTO processes VALUES ('TestProc', '', '', '', '', '[]', 'null', 0)")
        con.execute("INSERT INTO dimensions VALUES ('TestDim', false, 0, '[]', '{}', '[]', '[]')")
    finally:
        con.close()
    return db_path


# ---------------------------------------------------------------------------
# 数据源状态识别
# ---------------------------------------------------------------------------

def test_empty_when_no_data(isolated):
    """无本地数据 → EMPTY。"""
    s = ds.detect_current_source()
    assert s.type == ds.DataSourceType.EMPTY
    assert not s.has_data


def test_real_local_when_data_exists(isolated):
    """存在真实数据 → REAL_LOCAL，counts 动态读取。"""
    data_dir = isolated / "data"
    _make_real_db(data_dir)
    set_data_dir(str(data_dir))
    get_settings.cache_clear()
    s = ds.detect_current_source()
    assert s.type == ds.DataSourceType.REAL_LOCAL
    assert s.has_data
    assert s.counts["cubes"] == 1


def test_ensure_demo_when_empty(isolated):
    """无数据时 ensure_demo_if_empty 自动进入 Demo 模式。"""
    s = ds.ensure_demo_if_empty()
    assert s.type == ds.DataSourceType.DEMO
    assert s.counts["cubes"] == 3


def test_ensure_keeps_real_when_data_exists(isolated):
    """有真实数据时 ensure_demo_if_empty 不覆盖，保持 REAL_LOCAL。"""
    data_dir = isolated / "data"
    _make_real_db(data_dir)
    set_data_dir(str(data_dir))
    get_settings.cache_clear()
    s = ds.ensure_demo_if_empty()
    assert s.type == ds.DataSourceType.REAL_LOCAL


def test_demo_does_not_touch_real_data(isolated):
    """Demo 写入独立目录，绝不覆盖真实 data/。"""
    real_dir = isolated / "data"
    _make_real_db(real_dir)
    set_data_dir(str(real_dir))
    get_settings.cache_clear()

    # 切到 Demo
    ds.load_demo_data()
    # 真实 data/ 的 db 仍在（未被 demo drop）
    real_db = real_dir / "db" / "tm1_insight.duckdb"
    assert real_db.exists()
    con = duckdb.connect(str(real_db), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM cubes").fetchone()[0] == 1
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Demo 数据
# ---------------------------------------------------------------------------

def test_demo_data_loads(isolated):
    """Demo 数据能加载，且包含 cubes/processes/dimensions/chores。"""
    s = ds.load_demo_data()
    assert s.type == ds.DataSourceType.DEMO
    assert s.counts["cubes"] == 3
    assert s.counts["processes"] == 3
    assert s.counts["dimensions"] == 6
    assert s.counts["chores"] == 2


def test_demo_data_idempotent(isolated):
    """Demo 加载幂等（重复调用不报错）。"""
    ds.load_demo_data()
    s = ds.load_demo_data()
    assert s.type == ds.DataSourceType.DEMO
    assert s.counts["cubes"] == 3


def test_demo_dependencies_build(isolated):
    """Demo 数据能构建依赖（Graph / Impact 可用）。"""
    ds.load_demo_data()
    from tm1_insight.store.db import Store
    from tm1_insight.store.graph_adapter import dependencies_from_store
    store = Store(get_settings())
    con = store.connect(read_only=True)
    try:
        deps = dependencies_from_store(con)
    finally:
        con.close()
    assert len(deps) > 0


def test_demo_detect_returns_demo_type(isolated):
    """切到 Demo 后，detect_current_source 识别为 DEMO。"""
    ds.load_demo_data()
    s = ds.detect_current_source()
    assert s.type == ds.DataSourceType.DEMO


# ---------------------------------------------------------------------------
# 目录检测
# ---------------------------------------------------------------------------

def test_detect_valid_directory(isolated):
    """检测有效数据目录 → valid=True，counts 动态读取。"""
    data_dir = isolated / "data"
    _make_real_db(data_dir)
    r = ds.detect_directory(str(data_dir))
    assert r.valid
    assert r.has_duckdb
    assert r.counts["cubes"] == 1


def test_detect_nonexistent_directory(isolated):
    """检测不存在的目录 → valid=False + 明确错误。"""
    r = ds.detect_directory(str(isolated / "nope"))
    assert not r.valid
    assert "不存在" in r.error


def test_detect_invalid_directory(isolated):
    """检测无 DuckDB 的目录 → valid=False + 明确错误。"""
    empty = isolated / "empty"
    empty.mkdir()
    r = ds.detect_directory(str(empty))
    assert not r.valid
    assert "DuckDB" in r.error


# ---------------------------------------------------------------------------
# 数据源切换
# ---------------------------------------------------------------------------

def test_switch_demo_then_reset(isolated):
    """切换到 demo → DEMO；reset → 回到 EMPTY。"""
    ds.load_demo_data()
    assert ds.detect_current_source().type == ds.DataSourceType.DEMO
    set_data_dir(None)
    assert ds.detect_current_source().type == ds.DataSourceType.EMPTY


def test_switch_local_data(isolated):
    """切换到本地数据目录 → REAL_LOCAL。"""
    data_dir = isolated / "data"
    _make_real_db(data_dir)
    set_data_dir(str(data_dir))
    s = ds.detect_current_source()
    assert s.type == ds.DataSourceType.REAL_LOCAL
    assert s.counts["cubes"] == 1


def test_unavailable_explicit_source_does_not_silently_become_demo(isolated):
    set_data_dir(isolated / "unavailable-model")
    result = ds.ensure_demo_if_empty()
    assert result.type == ds.DataSourceType.EMPTY
    assert result.error
    assert get_settings().data_dir == isolated / "unavailable-model"
    assert not (isolated / "demo").exists()
