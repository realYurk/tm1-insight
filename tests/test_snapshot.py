"""Snapshot 基础设施（snapshot/）的回归测试。

覆盖：
1. create            创建快照
2. save              持久化
3. load              读取
4. round trip        save→load 内容一致
5. multiple          多个快照可同时存在
6. immutability      保存 B 不能覆盖 A
7. metadata          正确读取 metadata
8. schema version    当前版本检查
9. corruption        损坏快照显式报错
10. content hash     哈希稳定
11. small fixture    只使用小测试数据（不触碰真实 1.44GB 数据库）
12. no prod modify   全程使用临时目录
"""
from __future__ import annotations

import json

import pytest

from tm1_insight.snapshot import (
    SnapshotLoadError,
    SnapshotRecord,
    SnapshotStore,
    SUPPORTED_SCHEMA_VERSION,
)


@pytest.fixture
def store(tmp_path):
    """临时目录里的快照存储，隔离于真实 data/ 目录。"""
    return SnapshotStore(tmp_path / "snapshots")


def _payload():
    """最小可读的模型快照内容 fixture（几 KB 级别，绝不含生产数据）。"""
    return {
        "cubes": ["Cube_A", "Cube_B"],
        "dimensions": ["Dimension_Product", "Dimension_Year"],
        "processes": ["Process_Load", "Process_Calc"],
        "chores": ["Nightly_Load"],
    }


# ---------------------------------------------------------------------------
# 1~4. create / save / load / round trip
# ---------------------------------------------------------------------------
def test_create_and_load_round_trip(store):
    record = store.create_snapshot(
        snapshot_id="snap-001",
        instance_id="DEV",
        model_name="Finance",
        payload=_payload(),
        created_at="2026-10-11T16:00:00",
        object_counts={"cubes": 2, "processes": 2, "dimensions": 2, "chores": 1},
    )
    assert record.snapshot_id == "snap-001"
    assert record.instance_id == "DEV"
    assert record.model_name == "Finance"
    assert record.schema_version == SUPPORTED_SCHEMA_VERSION
    assert record.content_hash

    loaded_record, payload = store.load_snapshot("snap-001")
    assert loaded_record == record
    assert payload == _payload()


# ---------------------------------------------------------------------------
# 5. multiple snapshots coexist
# ---------------------------------------------------------------------------
def test_multiple_snapshots_coexist(store):
    store.create_snapshot("snap-A", "DEV", "Finance", payload=_payload())
    store.create_snapshot("snap-B", "DEV", "Finance", payload={"cubes": ["Cube_A"]})
    store.create_snapshot("snap-C", "PROD", "Finance", payload={})

    ids = [r.snapshot_id for r in store.list_snapshots()]
    assert ids == ["snap-A", "snap-B", "snap-C"]

    # 三者内容互不干扰
    _, pa = store.load_snapshot("snap-A")
    _, pb = store.load_snapshot("snap-B")
    _, pc = store.load_snapshot("snap-C")
    assert pa["cubes"] == ["Cube_A", "Cube_B"]
    assert pb["cubes"] == ["Cube_A"]
    assert pc == {}


# ---------------------------------------------------------------------------
# 6. immutability：保存 B 不能覆盖 A
# ---------------------------------------------------------------------------
def test_immutability_no_overwrite(store):
    store.create_snapshot("snap-A", "DEV", "Finance", payload=_payload())

    with pytest.raises(SnapshotLoadError):
        store.create_snapshot("snap-A", "DEV", "Finance", payload={"cubes": ["X"]})

    # 原内容保持不变
    _, payload = store.load_snapshot("snap-A")
    assert payload["cubes"] == ["Cube_A", "Cube_B"]


def test_save_into_existing_dir_rejected(store):
    store.create_snapshot("snap-A", "DEV", "Finance", payload=_payload())

    # 直接 save 到已存在目录也应拒绝（不静默覆盖）
    record = SnapshotRecord(
        snapshot_id="snap-A",
        instance_id="DEV",
        model_name="Finance",
    )
    with pytest.raises(SnapshotLoadError):
        store.save_snapshot("snap-A", {"cubes": ["Y"]}, record)


# ---------------------------------------------------------------------------
# 7. metadata
# ---------------------------------------------------------------------------
def test_metadata_round_trip(store):
    store.create_snapshot(
        "snap-meta", "TEST", "Sales",
        payload=_payload(),
        created_at="2026-10-11T10:00:00",
        object_counts={"cubes": 2, "processes": 2, "dimensions": 2, "chores": 1},
    )
    meta = store.load_metadata("snap-meta")
    assert meta.instance_id == "TEST"
    assert meta.model_name == "Sales"
    assert meta.created_at == "2026-10-11T10:00:00"
    assert meta.object_counts["cubes"] == 2
    assert meta.source == "tm1"


# ---------------------------------------------------------------------------
# 8. schema version 检查
# ---------------------------------------------------------------------------
def test_schema_version_supported(store):
    record = store.create_snapshot("snap-v1", "DEV", "M", payload={})
    assert record.schema_version == SUPPORTED_SCHEMA_VERSION
    # 当前版本可正常加载
    store.load_snapshot("snap-v1")


def test_schema_version_unsupported_rejected(store):
    store.create_snapshot("snap-v1", "DEV", "M", payload={})
    # 手动把 metadata 的 schema_version 抬到未来版本
    meta_path = store._metadata_path("snap-v1")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["schema_version"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(SnapshotLoadError, match="schema_version"):
        store.load_snapshot("snap-v1")


# ---------------------------------------------------------------------------
# 9. corruption 检测
# ---------------------------------------------------------------------------
def test_load_nonexistent_raises(store):
    with pytest.raises(SnapshotLoadError):
        store.load_snapshot("missing")


def test_missing_metadata_raises(store):
    store.create_snapshot("snap-x", "DEV", "M", payload={})
    store._metadata_path("snap-x").unlink()
    with pytest.raises(SnapshotLoadError, match="metadata"):
        store.load_snapshot("snap-x")


def test_corrupt_payload_raises(store):
    store.create_snapshot("snap-x", "DEV", "M", payload={"cubes": ["A"]})
    store._payload_path("snap-x").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SnapshotLoadError):
        store.load_snapshot("snap-x")


def test_hash_mismatch_raises(store):
    store.create_snapshot("snap-x", "DEV", "M", payload={"cubes": ["A"]})
    # 篡改 payload（仍为合法 JSON），哈希应不一致
    store._payload_path("snap-x").write_text(
        json.dumps({"cubes": ["A", "B"]}), encoding="utf-8"
    )
    with pytest.raises(SnapshotLoadError, match="哈希"):
        store.load_snapshot("snap-x")


def test_missing_required_metadata_field_raises(store):
    store.create_snapshot("snap-x", "DEV", "M", payload={})
    meta_path = store._metadata_path("snap-x")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["instance_id"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(SnapshotLoadError, match="instance_id"):
        store.load_snapshot("snap-x")


def test_snapshot_id_mismatch_raises(store):
    store.create_snapshot("snap-x", "DEV", "M", payload={})
    meta_path = store._metadata_path("snap-x")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["snapshot_id"] = "snap-other"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(SnapshotLoadError, match="不匹配"):
        store.load_snapshot("snap-x")


# ---------------------------------------------------------------------------
# 10. content hash 稳定
# ---------------------------------------------------------------------------
def test_content_hash_stable(store):
    r1 = store.create_snapshot("snap-h1", "DEV", "M", payload=_payload())
    r2 = store.create_snapshot("snap-h2", "DEV", "M", payload=_payload())
    assert r1.content_hash == r2.content_hash
    # 内容不同 → 哈希不同
    r3 = store.create_snapshot("snap-h3", "DEV", "M", payload={"cubes": ["Only_A"]})
    assert r3.content_hash != r1.content_hash


# ---------------------------------------------------------------------------
# 11~12. 只用小 fixture + 不触碰生产数据
# ---------------------------------------------------------------------------
def test_store_isolated_from_production(tmp_path):
    # 快照根目录完全在 tmp_path 下，与真实 data/ 无关
    store = SnapshotStore(tmp_path / "snapshots")
    store.create_snapshot("s1", "DEV", "M", payload=_payload())
    # 落盘位置确实在 tmp_path 内
    assert (tmp_path / "snapshots" / "s1" / "metadata.json").exists()
    assert (tmp_path / "snapshots" / "s1" / "payload.json").exists()


def test_snapshot_module_has_no_duckdb_dependency():
    import ast
    import tm1_insight.snapshot.store as ss

    with open(ss.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            assert not mod.startswith("tm1_insight.domain"), "snapshot store 不应依赖 domain"
            assert not mod.startswith("tm1_insight.api"), "snapshot store 不应依赖 api"
