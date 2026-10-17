"""Windows 长路径兼容性测试：验证长名称 TM1 对象的本地文件存储链路。

不连接真实 TM1 Server，全部通过本地临时目录验证「命名 → 写入 → 读取」真实链路。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tm1_insight.ingest.storage import (
    MANIFEST_NAME,
    MAX_PATH_SAFE,
    Manifest,
    resolve_object_path,
    short_stem,
)
from tm1_insight.ingest.exporter import save_json
from tm1_insight.ingest.loader import _load_json_dir

# 任务描述中的两个真实失败名称。
LONG_NAME_CALLER = (
    "Cub.MC Balance and Transfer PD Variance Analysis by Car Line."
    "Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Caller"
)
LONG_NAME_COMPARE = (
    "Cub.MC Balance and Transfer PD Variance Analysis by Car Line."
    "Data.Load.From.MC Balance and Transfer PD_Labor and Production Analysis.Compare"
)


def test_short_stem_is_deterministic():
    """同名对象稳定映射到同一短名。"""
    assert short_stem(LONG_NAME_CALLER, "processes") == short_stem(LONG_NAME_CALLER, "processes")
    assert short_stem(LONG_NAME_COMPARE, "processes") != short_stem(LONG_NAME_CALLER, "processes")


def test_short_stem_uses_sha256():
    """短名确实是 sha256 前 16 位 hex，且带对象类型前缀。"""
    digest = hashlib.sha256(LONG_NAME_CALLER.encode("utf-8")).hexdigest()[:16]
    assert short_stem(LONG_NAME_CALLER, "processes") == f"p_{digest}"


def _long_raw_dir() -> Path:
    """模拟 Windows 风格的长项目根目录（约 100+ 字符）。"""
    return Path(
        "D:/3.PA_Software/2.tools/tm1-insight-codex-cube-centric-reverse-engineering/"
        "collections/model-6q3gk8k1"
    )


def test_two_real_names_trigger_short_path():
    """两个真实长名称在长根目录下必须启用短名，且完整路径不再超限。"""
    raw_dir = _long_raw_dir()
    for name in (LONG_NAME_CALLER, LONG_NAME_COMPARE):
        plain = raw_dir / "processes" / f"{name}.json"
        assert len(str(plain)) > MAX_PATH_SAFE, "测试前提：原名路径确实超限"

        filepath, used_short = resolve_object_path(raw_dir, "processes", name)
        assert used_short is True
        assert len(str(filepath)) <= MAX_PATH_SAFE
        # 短名文件不含原始超长名称，但含确定性哈希前缀
        assert filepath.name.startswith("p_")
        assert filepath.suffix == ".json"


def test_short_name_keeps_original_filename():
    """普通名称不超限时，保持原名（人类可读）。"""
    raw_dir = _long_raw_dir()
    filepath, used_short = resolve_object_path(raw_dir, "processes", "SimpleProcess")
    assert used_short is False
    assert filepath.name == "SimpleProcess.json"


def test_export_then_read_back_by_original_name(tmp_path):
    """导出后能按原始名称重新读取对象（完整名称不截断）。

    真实链路：resolve_object_path -> save_json -> _load_json_dir -> 按 name 找到。
    """
    raw_dir = tmp_path / "raw"
    filepath, used_short = resolve_object_path(raw_dir, "processes", LONG_NAME_CALLER)
    payload = {
        "name": LONG_NAME_CALLER,
        "prolog": "",
        "metadata": "",
        "data": "CellPutN('Cube', 1);",
        "epilog": "",
        "parameters": [],
        "datasource": None,
    }
    save_json(payload, filepath)

    loaded = _load_json_dir(raw_dir, "processes")
    assert len(loaded) == 1
    # 原始名称完整保留，未截断
    assert loaded[0]["name"] == LONG_NAME_CALLER
    assert len(loaded[0]["name"]) == len(LONG_NAME_CALLER)


def test_distinct_names_do_not_overwrite(tmp_path):
    """不同原始名称不会因截断而互相覆盖。"""
    raw_dir = tmp_path / "raw"
    p1, _ = resolve_object_path(raw_dir, "processes", LONG_NAME_CALLER)
    p2, _ = resolve_object_path(raw_dir, "processes", LONG_NAME_COMPARE)
    assert p1 != p2
    save_json({"name": LONG_NAME_CALLER}, p1)
    save_json({"name": LONG_NAME_COMPARE}, p2)

    loaded = _load_json_dir(raw_dir, "processes")
    names = sorted(x["name"] for x in loaded)
    assert names == sorted([LONG_NAME_CALLER, LONG_NAME_COMPARE])


def test_manifest_registers_and_saves(tmp_path):
    """manifest 记录原始名称与短名映射，且被 loader 跳过（_ 前缀）。"""
    raw_dir = tmp_path / "raw"
    m = Manifest(raw_dir)
    stem = m.register(LONG_NAME_CALLER, "processes", True)
    m.save()

    manifest_path = raw_dir / MANIFEST_NAME
    assert manifest_path.exists()
    assert manifest_path.name.startswith("_")

    # loader 读取 processes 目录时，manifest（_ 前缀）不应被当作 Process
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["entries"][LONG_NAME_CALLER] == stem

    # 重新加载 manifest 得到一致映射
    m2 = Manifest.load(raw_dir)
    assert m2._entries[LONG_NAME_CALLER] == stem


def test_manifest_load_missing_returns_empty(tmp_path):
    """manifest 不存在时返回空 manifest（旧数据场景）。"""
    m = Manifest.load(tmp_path / "raw")
    assert m._entries == {}


def test_manifest_load_corrupt_does_not_crash(tmp_path):
    """manifest 损坏时明确降级为空，而非崩溃。"""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / MANIFEST_NAME).write_text("{ not valid json", encoding="utf-8")
    m = Manifest.load(raw_dir)
    assert m._entries == {}


def test_hash_collision_raises(tmp_path):
    """哈希冲突时必须明确报错，不得静默覆盖。"""
    m = Manifest(tmp_path / "raw")
    # 用 monkeypatch 伪造两个不同名称产生同一短名
    import tm1_insight.ingest.storage as storage_mod

    original = storage_mod.short_stem
    calls = {"n": 0}

    def fake_short_stem(name, obj_type):
        # 第一次调用返回正常，之后强制返回相同 stem 模拟冲突
        return "p_collision"

    storage_mod.short_stem = fake_short_stem
    try:
        m.register("NameA", "processes", True)
        with pytest.raises(RuntimeError, match="冲突"):
            m.register("NameB", "processes", True)
    finally:
        storage_mod.short_stem = original


def test_old_style_long_filename_still_readable(tmp_path):
    """旧版原始长名文件（历史导出）仍可读取，无需迁移。"""
    raw_dir = tmp_path / "raw"
    (raw_dir / "processes").mkdir(parents=True, exist_ok=True)
    # 旧格式：文件名 = 完整对象名 + .json（无短名）
    old_path = raw_dir / "processes" / f"{LONG_NAME_CALLER}.json"
    save_json({"name": LONG_NAME_CALLER, "data": "old data"}, old_path)

    loaded = _load_json_dir(raw_dir, "processes")
    assert len(loaded) == 1
    assert loaded[0]["name"] == LONG_NAME_CALLER


def test_index_file_not_treated_as_process(tmp_path):
    """_index.json / _manifest.json 不会被误认为普通 Process。"""
    raw_dir = tmp_path / "raw"
    (raw_dir / "processes").mkdir(parents=True, exist_ok=True)
    save_json({"processes": [LONG_NAME_CALLER]}, raw_dir / "processes" / "_index.json")
    save_json({"entries": {}}, raw_dir / "processes" / "_manifest.json")
    save_json({"name": "RealProcess"}, raw_dir / "processes" / "RealProcess.json")

    loaded = _load_json_dir(raw_dir, "processes")
    names = [x.get("name") for x in loaded]
    assert names == ["RealProcess"]


def test_all_object_types_share_mechanism():
    """其他对象类型（cubes/dimensions/chores）复用同一短名机制。"""
    for obj_type, prefix in (("cubes", "c"), ("dimensions", "d"), ("chores", "ch")):
        long_name = "A very long object name " + obj_type + " " + "X" * 200
        raw_dir = _long_raw_dir()
        filepath, used_short = resolve_object_path(raw_dir, obj_type, long_name)
        assert used_short is True
        assert filepath.name.startswith(f"{prefix}_")
