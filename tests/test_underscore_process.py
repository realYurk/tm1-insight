"""下划线开头 Process 修复回归测试。

根因：loader 旧逻辑用 ``fn.name.startswith("_")`` 跳过所有下划线开头的 JSON 文件，
导致 ``_CubeProcessFeeders`` 等 5 个合法 Process 被静默丢弃（3442 → 3437）。

修复后：只精确排除保留元数据文件名（_index.json / _manifest.json / _reconcile.json），
不再按下划线前缀排除业务对象。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tm1_insight.ingest.loader import (
    RESERVED_METADATA_FILES,
    _load_json_dir,
    _reconcile_names,
)
from tm1_insight.ingest.exporter import save_json

# 任务中报告缺失的 5 个下划线开头 Process。
UNDERSCORE_PROCESSES = [
    "_CubeProcessFeeders",
    "_New_Process_Template",
    "_New_Process_Template_Aruis",
    "_New_Template_2",
    "_New_Template_Alan_2",
]


def _make_process(name: str) -> dict:
    return {
        "name": name,
        "prolog": "",
        "metadata": "",
        "data": f"CellPutN('Cube', 1); /* {name} */",
        "epilog": "",
        "parameters": [],
        "datasource": None,
    }


# ---- 1~3. 五个下划线开头 Process 能正常加载 ----


@pytest.mark.parametrize("name", UNDERSCORE_PROCESSES)
def test_underscore_process_is_loaded(tmp_path, name):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    save_json(_make_process(name), raw / "processes" / f"{name}.json")

    rows, failures = _load_json_dir(raw, "processes")
    assert failures == []
    assert [r["name"] for r in rows] == [name]


def test_all_five_underscore_processes_loaded_together(tmp_path):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    for name in UNDERSCORE_PROCESSES:
        save_json(_make_process(name), raw / "processes" / f"{name}.json")

    rows, failures = _load_json_dir(raw, "processes")
    assert failures == []
    assert sorted(r["name"] for r in rows) == sorted(UNDERSCORE_PROCESSES)


# ---- 4. 保留文件不会被当作业务对象 ----


def test_reserved_metadata_files_excluded(tmp_path):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    # 精确保留名被排除
    save_json({"processes": []}, raw / "processes" / "_index.json")
    save_json({"entries": {}}, raw / "processes" / "_manifest.json")
    save_json({"processes": {}}, raw / "processes" / "_reconcile.json")
    # 下划线开头但非保留名的业务对象保留
    save_json(_make_process("_CubeProcessFeeders"), raw / "processes" / "_CubeProcessFeeders.json")

    rows, failures = _load_json_dir(raw, "processes")
    assert [r["name"] for r in rows] == ["_CubeProcessFeeders"]


def test_reserved_set_is_exact():
    assert "_CubeProcessFeeders.json" not in RESERVED_METADATA_FILES
    assert "_New_Process_Template.json" not in RESERVED_METADATA_FILES
    assert "_index.json" in RESERVED_METADATA_FILES


# ---- 5. 普通名称 Process 仍正常加载 ----


def test_normal_process_still_loaded(tmp_path):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    save_json(_make_process("NormalProcess"), raw / "processes" / "NormalProcess.json")
    rows, failures = _load_json_dir(raw, "processes")
    assert [r["name"] for r in rows] == ["NormalProcess"]


# ---- 6. 不同 Process 不因文件名映射相互覆盖 ----


def test_underscore_and_plain_do_not_overwrite(tmp_path):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    save_json(_make_process("_New_Process_Template"), raw / "processes" / "_New_Process_Template.json")
    save_json(_make_process("New_Process_Template"), raw / "processes" / "New_Process_Template.json")

    rows, failures = _load_json_dir(raw, "processes")
    names = sorted(r["name"] for r in rows)
    assert names == sorted(["_New_Process_Template", "New_Process_Template"])


# ---- 7. 缺失/损坏 JSON 不被静默当作成功 ----


def test_corrupt_json_not_silently_successful(tmp_path):
    raw = tmp_path / "raw"
    (raw / "processes").mkdir(parents=True)
    save_json(_make_process("_Good"), raw / "processes" / "_Good.json")
    (raw / "processes" / "_Bad.json").write_text("{ corrupt", encoding="utf-8")

    rows, failures = _load_json_dir(raw, "processes")
    assert [r["name"] for r in rows] == ["_Good"]
    assert failures == ["_Bad.json"]


# ---- 8. 3442 个唯一 Process 全部入库时校验通过 ----


def test_reconcile_passes_at_full_3442(tmp_path):
    from tm1_insight.api.app import _validate_collected_model

    # 3442 个名称：5 个下划线 + 其余普通
    names = list(UNDERSCORE_PROCESSES) + [f"P{i:04d}" for i in range(3442 - len(UNDERSCORE_PROCESSES))]
    assert len(names) == 3442

    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json({"processes": names}, raw / "_index.json")
    save_json(
        {"processes": {"expected_count": 3442, "actual_unique": 3442,
                       "actual_rows": 3442, "missing": [], "duplicates": [],
                       "read_failures": []}},
        raw / "_reconcile.json",
    )

    staged = MagicMock()
    staged.raw_dir = raw
    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    _validate_collected_model(staged, exported, actual)  # 不抛


# ---- 9. 3437 时仍拒绝切换正式数据源 ----


def test_validate_rejects_at_3437(tmp_path):
    from tm1_insight.api.app import _validate_collected_model

    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    save_json(
        {"processes": {"expected_count": 3442, "actual_unique": 3437,
                       "actual_rows": 3437, "missing": UNDERSCORE_PROCESSES,
                       "duplicates": [], "read_failures": []}},
        raw / "_reconcile.json",
    )

    staged = MagicMock()
    staged.raw_dir = raw
    exported = {"cubes": 100, "processes": 3442, "dimensions": 12013, "chores": 67}
    actual = {"cubes": 100, "processes": 3437, "dimensions": 12013, "chores": 67}

    with pytest.raises(ValueError) as exc:
        _validate_collected_model(staged, exported, actual)
    msg = str(exc.value)
    assert "3442" in msg and "3437" in msg
    # 缺失的下划线对象名出现在报错中
    for name in UNDERSCORE_PROCESSES:
        assert name in msg
