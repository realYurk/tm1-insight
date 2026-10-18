"""名称级对账测试：精确定位 3442 vs 3437 这类「计数差 5 但说不出少了谁」的问题。

核心不变量：对象计数校验必须能回答「哪些对象、在哪一环节丢失」，而非只报数量差。
全部离线，用 mock 数据覆盖真实丢失环节：
1. 导出失败未落盘（failed_<type>.txt）
2. 文件写入成功但读不回（损坏 JSON）
3. 同名覆盖（processes.name PRIMARY KEY）
4. 枚举名 vs 实际入库名差集（_index.json + _reconcile.json）
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tm1_insight.ingest.loader import (
    _index_names,
    _reconcile_names,
    _load_json_dir,
)
from tm1_insight.ingest.exporter import save_json


# ---- 单元：_index_names / _reconcile_names ----


def test_index_names_reads_enumeration(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json({"processes": ["P1", "P2", "P3"]}, raw / "_index.json")
    assert _index_names(raw, "processes") == ["P1", "P2", "P3"]


def test_index_names_missing_returns_empty(tmp_path):
    assert _index_names(tmp_path / "raw", "processes") == []


def test_reconcile_detects_missing_names(tmp_path):
    """枚举 3 个，实际读入 2 个 → 精确报出缺失的那一个。"""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json({"processes": ["P1", "P2", "P3"]}, raw / "_index.json")
    loaded = [{"name": "P1"}, {"name": "P2"}]
    rec = _reconcile_names(raw, "processes", loaded, [])
    assert rec["expected_count"] == 3
    assert rec["actual_unique"] == 2
    assert rec["missing"] == ["P3"]


def test_reconcile_detects_duplicate_names(tmp_path):
    """同名对象读入两次 → 重复名单精确报出（对应 PRIMARY KEY 覆盖风险）。"""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json({"processes": ["P1", "P2"]}, raw / "_index.json")
    loaded = [{"name": "P1"}, {"name": "P1"}, {"name": "P2"}]
    rec = _reconcile_names(raw, "processes", loaded, [])
    assert rec["duplicates"] == ["P1"]
    assert rec["actual_rows"] == 3  # 行数 > 唯一数
    assert rec["actual_unique"] == 2


def test_reconcile_read_failure_reported_as_missing(tmp_path):
    """文件写入成功但读不回（损坏 JSON）→ 被记为缺失证据，不静默跳过。"""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json({"processes": ["P1", "P2"]}, raw / "_index.json")
    loaded = [{"name": "P1"}]
    rec = _reconcile_names(raw, "processes", loaded, ["P2.json"])
    assert "P2" in rec["missing"]
    assert rec["read_failures"] == ["P2.json"]


def test_load_json_dir_reports_read_failure(tmp_path):
    """损坏的 JSON 文件被 _load_json_dir 记入失败清单，而非静默跳过。"""
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    save_json({"name": "Good"}, raw / "processes" / "Good.json")
    (raw / "processes" / "Bad.json").write_text("{ not valid json", encoding="utf-8")

    rows, failures = _load_json_dir(raw, "processes")
    assert [r["name"] for r in rows] == ["Good"]
    assert failures == ["Bad.json"]


# ---- 集成：校验层能从对账结果精确报告缺失对象名 ----


def test_validate_reports_missing_names_from_reconcile(tmp_path):
    """_validate_collected_model 优先用 _reconcile.json 报缺失对象名。"""
    from tm1_insight.api.app import _validate_collected_model

    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    staged.raw_dir.mkdir(parents=True)
    save_json(
        {
            "processes": {
                "expected_count": 3442,
                "actual_unique": 3437,
                "actual_rows": 3437,
                "missing": [
                    "Cub.MC Balance and Transfer PD Variance Analysis by Car Line."
                    "Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Caller",
                    "Cub.MC Balance and Transfer PD Variance Analysis by Car Line."
                    "Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Compare",
                ],
                "duplicates": [],
                "read_failures": [],
            }
        },
        staged.raw_dir / "_reconcile.json",
    )

    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 100, "processes": 3437, "dimensions": 12013, "chores": 67}

    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)

    msg = str(exc.value)
    assert "3442" in msg and "3437" in msg
    # 具体缺失对象名必须出现在报错中
    assert "Caller" in msg and "Compare" in msg


def test_validate_falls_back_to_failed_file_when_no_reconcile(tmp_path):
    """无 _reconcile.json 时回退到 failed_<type>.txt 证据（向后兼容）。"""
    from tm1_insight.api.app import _validate_collected_model

    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    staged.raw_dir.mkdir(parents=True)
    (staged.raw_dir / "failed_processes.txt").write_text(
        "LostProcess\tfile_save:FileNotFoundError\n", encoding="utf-8"
    )

    exported = {"cubes": 10, "processes": 10, "dimensions": 10, "chores": 1}
    actual = {"cubes": 10, "processes": 9, "dimensions": 10, "chores": 1}

    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)
    assert "LostProcess" in str(exc.value)


def test_validate_passes_when_reconcile_shows_no_missing(tmp_path):
    """对账结果无缺失且计数一致时，校验通过，不误报。"""
    from tm1_insight.api.app import _validate_collected_model

    staged = MagicMock()
    staged.raw_dir = tmp_path / "raw"
    staged.raw_dir.mkdir(parents=True)
    save_json(
        {
            "processes": {
                "expected_count": 10,
                "actual_unique": 10,
                "actual_rows": 10,
                "missing": [],
                "duplicates": [],
                "read_failures": [],
            }
        },
        staged.raw_dir / "_reconcile.json",
    )
    exported = {"cubes": 10, "processes": 10, "dimensions": 10, "chores": 1}
    actual = {"cubes": 10, "processes": 10, "dimensions": 10, "chores": 1}
    _validate_collected_model(staged, exported, actual)  # 不抛


# ---- 真实链路：长名称 Process 从保存到读回 + 对账完整 ----


def test_long_name_full_chain_reconciles(tmp_path):
    """长名称 Process 经 resolve_object_path 短名落盘后，名称级对账无缺失。"""
    from tm1_insight.ingest.storage import resolve_object_path

    LONG = (
        "Cub.MC Balance and Transfer PD Variance Analysis by Car Line."
        "Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Caller"
    )
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    # 用长根目录触发短名
    raw_long = Path("D:/3.PA_Software/2.tools/tm1-insight-codex-cube-centric-reverse-engineering/"
                    "collections/model-9pmjh8jx")
    filepath, used_short = resolve_object_path(raw_long, "processes", LONG)
    assert used_short is True

    # 枚举清单写入
    save_json({"processes": [LONG]}, raw / "_index.json")

    # 模拟实际落盘到临时 raw（用短名逻辑对应关系）
    save_json({"name": LONG, "data": "CellPutN('Cube',1);"}, raw / "processes" / filepath.name)

    rows, failures = _load_json_dir(raw, "processes")
    assert failures == []
    rec = _reconcile_names(raw, "processes", rows, failures)
    assert rec["missing"] == []
    assert rec["actual_unique"] == 1
    assert rows[0]["name"] == LONG  # 名称完整未截断
