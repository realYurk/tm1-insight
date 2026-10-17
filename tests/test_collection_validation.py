"""Collection Validation 校验逻辑测试：验证采集结果计数校验与失败诊断。

不连接 TM1 Server，全部用 mock 数据离线复现「采集不完整导致 ValueError」的根因，
并验证修复后的校验逻辑能精确定位失败对象类型与缺失对象。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tm1_insight.api.app import _validate_collected_model


def _staged_with_failed(failed_by_type: dict[str, list[str]], tmp_path: Path) -> MagicMock:
    """构造一个带 failed_<type>.txt 的 staged settings mock。"""
    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    for key, names in failed_by_type.items():
        p = staged.raw_dir / f"failed_{key}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(f"{n}\tfile_save:FileNotFoundError\n" for n in names), encoding="utf-8")
    return staged


def test_reconcile_passes_when_counts_match(tmp_path):
    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    # 不应抛异常
    _validate_collected_model(staged, exported, actual)


def test_reconcile_raises_on_process_count_mismatch(tmp_path):
    """复现根因：3442 枚举 vs 3440 入库（两个长名称 Process 失败）。"""
    staged = _staged_with_failed({"processes": [
        "Cub.MC Balance and Transfer PD Variance Analysis by Car Line.Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Caller",
        "Cub.MC Balance and Transfer PD Variance Analysis by Car Line.Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Compare",
    ]}, tmp_path)
    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 100, "processes": 3440, "dimensions": 12013, "chores": 67}

    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)

    msg = str(exc.value)
    assert "processes" in msg
    assert "3442" in msg and "3440" in msg
    # 缺失对象名应体现在报错中
    assert "Caller" in msg and "Compare" in msg


def test_reconcile_raises_on_dimension_count_mismatch(tmp_path):
    staged = _staged_with_failed({"dimensions": ["LongDimensionName" * 10]}, tmp_path)
    exported = {"cubes": 10, "processes": 5, "dimensions": 100, "chores": 3}
    actual = {"cubes": 10, "processes": 5, "dimensions": 99, "chores": 3}

    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)
    assert "dimensions" in str(exc.value)


def test_reconcile_raises_when_no_cubes(tmp_path):
    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    exported = {"cubes": 0, "processes": 5, "dimensions": 3, "chores": 1}
    actual = {"cubes": 0, "processes": 5, "dimensions": 3, "chores": 1}
    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)
    assert "Cube" in str(exc.value)


def test_reconcile_reports_all_mismatched_keys(tmp_path):
    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 99, "processes": 3441, "dimensions": 12010, "chores": 67}
    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)
    msg = str(exc.value)
    assert "cubes" in msg and "processes" in msg and "dimensions" in msg


def test_failed_file_absent_is_handled(tmp_path):
    """failed 文件不存在时不报错，仍正常校验计数。"""
    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    exported = {"cubes": 5, "processes": 5, "dimensions": 5, "chores": 1}
    actual = {"cubes": 5, "processes": 5, "dimensions": 5, "chores": 1}
    _validate_collected_model(staged, exported, actual)  # 不抛


def test_validate_failure_prevents_activate(tmp_path, monkeypatch):
    """校验失败时不得切换正式数据源；只有校验通过才允许 activate。

    验证 _run_ingest 的核心不变量：_validate_collected_model 抛 ValueError 时，
    activate_collected_source 不会被调用。
    """
    import importlib
    import tm1_insight.ingest.exporter as exporter_mod
    import tm1_insight.ingest.loader as loader_mod
    import tm1_insight.store.db as db_mod
    import tm1_insight.config as config_mod

    # 获取真正的 app 模块（tm1_insight.api.app 被包重新导出为 FastAPI 对象）
    app_mod = importlib.import_module("tm1_insight.api.app")

    calls = {"activate": 0}

    # mock 掉 _run_ingest 内部局部 import 的来源
    fake_exporter = MagicMock()
    fake_exporter.export_all.return_value = {
        "cubes": 10, "processes": 10, "dimensions": 10, "chores": 1, "raw_dir": str(tmp_path / "raw"),
    }
    monkeypatch.setattr(exporter_mod, "Exporter", lambda *a, **k: fake_exporter)

    fake_loader = MagicMock()
    fake_loader.load.return_value = {}
    monkeypatch.setattr(loader_mod, "Loader", lambda *a, **k: fake_loader)

    # Store.all_rows 返回空 cubes，触发 _validate_collected_model 的 ValueError
    fake_store = MagicMock()
    fake_store.all_rows.return_value = {"cubes": 0, "processes": 0, "dimensions": 0, "chores": 0}
    monkeypatch.setattr(db_mod, "Store", lambda *a, **k: fake_store)

    def fake_activate(*args, **kwargs):
        calls["activate"] += 1
    monkeypatch.setattr(config_mod, "activate_collected_source", fake_activate)

    settings = MagicMock()
    settings.user_data_root = tmp_path
    settings.db_path = tmp_path / "active.duckdb"
    settings.model_copy.return_value = settings

    app_mod._run_ingest(settings)

    # 校验失败 → activate 未被调用，正式数据源保持不变
    assert calls["activate"] == 0
