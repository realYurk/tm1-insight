"""TM1 Collector（collector.py）的回归测试。

覆盖（对应 Task 9 要求）：
1.  Process collection
2.  Process parameters
3.  Prolog / Metadata / Data / Epilog
4.  Cube collection
5.  Dimension collection
6.  Rule collection
7.  Empty collections
8.  Canonical payload validation
9.  Mock TM1 client
10. Server failure
11. Missing optional metadata
12. Deterministic output
13. No real TM1 connection
14. Snapshot integration
15. Existing tests regression（全量 pytest 保证）

测试使用 fake client（依赖注入），不连接真实 TM1 Server、不扫描真实 DuckDB。
"""
from __future__ import annotations

import json

import pytest

from tm1_insight.collector import TM1Collector, collect_snapshot
from tm1_insight.snapshot import SnapshotStore, validate_snapshot_payload


# ---------------------------------------------------------------------------
# Fake client（mock 数据源，不连真实 TM1）
# ---------------------------------------------------------------------------
class FakeClient:
    """模拟 TM1Client 的最小面：返回固定 raw dict，可注入失败。"""

    def __init__(self, processes=None, cubes=None, dimensions=None, names=None,
                 fail_on=None):
        self.processes = processes or {}
        self.cubes = cubes or {}
        self.dimensions = dimensions or {}
        self.names = names or {
            "cubes": list(self.cubes.keys()),
            "processes": list(self.processes.keys()),
            "dimensions": list(self.dimensions.keys()),
        }
        self.fail_on = fail_on or {}  # {"processes": "P_X", ...} → 抛异常
        self.calls = {"fetch_process": 0, "fetch_cube": 0, "fetch_dimension": 0}

    def list_all_names(self):
        return self.names

    def fetch_process(self, tm1, name):
        self.calls["fetch_process"] += 1
        if self.fail_on.get("processes") == name:
            raise ConnectionError(f"模拟服务器失败: {name}")
        return self.processes[name]

    def fetch_cube(self, tm1, name):
        self.calls["fetch_cube"] += 1
        if self.fail_on.get("cubes") == name:
            raise ConnectionError(f"模拟服务器失败: {name}")
        return self.cubes[name]

    def fetch_dimension(self, tm1, name, is_system):
        self.calls["fetch_dimension"] += 1
        if self.fail_on.get("dimensions") == name:
            raise ConnectionError(f"模拟服务器失败: {name}")
        return self.dimensions[name]


def _raw_process(name="P_Load", **kw):
    base = {
        "name": name,
        "parameters": [{"name": "pCube", "type": "String", "default_value": ""}],
        "prolog": "vCube = 'Cube_A';",
        "metadata": "",
        "data": "CellPutN(1, vCube, '2024', 'Measure');",
        "epilog": "",
    }
    base.update(kw)
    return base


def _raw_cube(name="Cube_A", dimensions=("Dim_A", "Dim_B"), rules=""):
    return {"name": name, "dimensions": list(dimensions), "rules": rules,
            "has_rules": bool(rules)}


def _raw_dimension(name="Dim_A", elements=None, subsets=None):
    return {
        "name": name,
        "elements": elements or [{"name": "E1", "type": "Numeric"},
                                 {"name": "E2", "type": "Numeric"}],
        "subsets": subsets or [{"name": "All", "expression": ""}],
    }


# ---------------------------------------------------------------------------
# 1~3. Process collection（parameters / 四段）
# ---------------------------------------------------------------------------
def test_process_collection():
    client = FakeClient(processes={"P_Load": _raw_process("P_Load")})
    payload = collect_snapshot(client)

    assert len(payload["processes"]) == 1
    p = payload["processes"][0]
    assert p["name"] == "P_Load"


def test_process_parameters_mapped():
    client = FakeClient(processes={
        "P": _raw_process("P", parameters=[
            {"name": "pCube", "type": "String", "default_value": ""},
            {"name": "pVersion", "type": "String", "default_value": "2026"},
        ]),
    })
    payload = collect_snapshot(client)
    p = payload["processes"][0]
    # canonical 只保留 name，裁剪 type/default_value
    assert p["parameters"] == [{"name": "pCube"}, {"name": "pVersion"}]


def test_process_four_sections_preserved():
    raw = _raw_process(
        "P",
        prolog="prolog_code;",
        metadata="metadata_code;",
        data="data_code;",
        epilog="epilog_code;",
    )
    client = FakeClient(processes={"P": raw})
    payload = collect_snapshot(client)
    p = payload["processes"][0]

    assert p["prolog"] == "prolog_code;"
    assert p["metadata"] == "metadata_code;"
    assert p["data"] == "data_code;"
    assert p["epilog"] == "epilog_code;"


# ---------------------------------------------------------------------------
# 4. Cube collection
# ---------------------------------------------------------------------------
def test_cube_collection():
    client = FakeClient(cubes={"Cube_A": _raw_cube("Cube_A", ("Dim_A", "Dim_B"))})
    payload = collect_snapshot(client)

    assert len(payload["cubes"]) == 1
    c = payload["cubes"][0]
    assert c["name"] == "Cube_A"
    assert c["dimensions"] == ["Dim_A", "Dim_B"]


def test_cube_rules_array_mapping():
    client = FakeClient(cubes={"Cube_A": _raw_cube("Cube_A", rules="['X']=N:...;")})
    payload = collect_snapshot(client)
    c = payload["cubes"][0]
    # canonical rules 是 array；有文本时包成单元素数组
    assert c["rules"] == ["['X']=N:...;"]


# ---------------------------------------------------------------------------
# 5. Dimension collection
# ---------------------------------------------------------------------------
def test_dimension_collection():
    client = FakeClient(dimensions={
        "Dim_A": _raw_dimension("Dim_A", elements=[{"name": "E1", "type": "Numeric"}],
                                subsets=[{"name": "All", "expression": ""}]),
    })
    payload = collect_snapshot(client)

    assert len(payload["dimensions"]) == 1
    d = payload["dimensions"][0]
    assert d["name"] == "Dim_A"
    # elements/subsets 裁剪为 string list
    assert d["elements"] == ["E1"]
    assert d["subsets"] == ["All"]


# ---------------------------------------------------------------------------
# 6. Rule collection
# ---------------------------------------------------------------------------
def test_rule_collection_from_cube():
    client = FakeClient(cubes={"Cube_A": _raw_cube("Cube_A", rules="['X']=N:DB('Cube_B',...);")})
    payload = collect_snapshot(client)

    # 有规则的 cube 派生一条 Rule，referenced_cubes 不解析（留空）
    assert len(payload["rules"]) == 1
    r = payload["rules"][0]
    assert r["cube"] == "Cube_A"
    assert r["statement"] == "['X']=N:DB('Cube_B',...);"
    assert r["referenced_cubes"] == []


def test_no_rule_when_cube_has_no_rules():
    client = FakeClient(cubes={"Cube_A": _raw_cube("Cube_A", rules="")})
    payload = collect_snapshot(client)
    assert payload["rules"] == []


# ---------------------------------------------------------------------------
# 7. Empty collections
# ---------------------------------------------------------------------------
def test_empty_collections():
    client = FakeClient(names={"cubes": [], "processes": [], "dimensions": []})
    payload = collect_snapshot(client)

    assert payload == {"processes": [], "rules": [], "cubes": [], "dimensions": []}
    validate_snapshot_payload(payload)  # 合法


# ---------------------------------------------------------------------------
# 8. Canonical payload validation
# ---------------------------------------------------------------------------
def test_collected_payload_passes_validation():
    client = FakeClient(
        processes={"P": _raw_process("P")},
        cubes={"Cube_A": _raw_cube("Cube_A", rules="...")},
        dimensions={"Dim_A": _raw_dimension("Dim_A")},
    )
    payload = collect_snapshot(client)
    validate_snapshot_payload(payload)  # 不抛异常


# ---------------------------------------------------------------------------
# 9. Mock TM1 client（已通过 FakeClient 体现，这里显式验证协议面）
# ---------------------------------------------------------------------------
def test_collector_accepts_duck_typed_client():
    # 任意实现 fetch 协议的对象都能作为 client（不强制 TM1Client/TM1py）
    class MinimalClient:
        def list_all_names(self):
            return {"cubes": [], "processes": ["P"], "dimensions": []}

        def fetch_process(self, tm1, name):
            return _raw_process(name)

        def fetch_cube(self, tm1, name):
            return _raw_cube(name)

        def fetch_dimension(self, tm1, name, is_system):
            return _raw_dimension(name)

    collector = TM1Collector(MinimalClient(), tm1=None)
    payload = collector.collect_snapshot()
    assert payload["processes"][0]["name"] == "P"


# ---------------------------------------------------------------------------
# 10. Server failure
# ---------------------------------------------------------------------------
def test_server_failure_propagates():
    client = FakeClient(
        processes={"P": _raw_process("P")},
        fail_on={"processes": "P"},
    )
    with pytest.raises(ConnectionError):
        collect_snapshot(client)


# ---------------------------------------------------------------------------
# 11. Missing optional metadata
# ---------------------------------------------------------------------------
def test_missing_optional_metadata_keeps_valid_schema():
    # 缺 rules / subsets / parameters 等可选字段，仍产出合法 payload
    client = FakeClient(
        processes={"P": {"name": "P", "prolog": "", "metadata": "", "data": "", "epilog": ""}},
        cubes={"Cube_A": {"name": "Cube_A", "dimensions": ["Dim_A"]}},
        dimensions={"Dim_A": {"name": "Dim_A"}},
    )
    payload = collect_snapshot(client)
    validate_snapshot_payload(payload)  # 不抛异常
    # 缺字段不伪造
    assert payload["cubes"][0]["rules"] == []
    assert payload["dimensions"][0]["elements"] == []


# ---------------------------------------------------------------------------
# 12. Deterministic output
# ---------------------------------------------------------------------------
def test_deterministic_output():
    client = FakeClient(
        processes={"P_A": _raw_process("P_A"), "P_B": _raw_process("P_B")},
        cubes={"Cube_A": _raw_cube("Cube_A", rules="r1")},
        dimensions={"Dim_A": _raw_dimension("Dim_A")},
    )
    r1 = collect_snapshot(client)
    r2 = collect_snapshot(client)
    assert r1 == r2


# ---------------------------------------------------------------------------
# 13. No real TM1 connection
# ---------------------------------------------------------------------------
def test_no_real_tm1_connection():
    # 整个测试套件不 import TM1py、不 connect；本用例显式确认 collector 模块
    # 未 import TM1py（保持可 mock / 离线可测）
    import ast
    import tm1_insight.collector as col

    with open(col.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "TM1py", "collector 不应 import TM1py"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("TM1py"), "collector 不应 from TM1py import"


# ---------------------------------------------------------------------------
# 14. Snapshot integration（薄集成：payload → SnapshotStore）
# ---------------------------------------------------------------------------
def test_snapshot_integration(tmp_path):
    client = FakeClient(
        processes={"P": _raw_process("P")},
        cubes={"Cube_A": _raw_cube("Cube_A")},
        dimensions={"Dim_A": _raw_dimension("Dim_A")},
    )
    payload = collect_snapshot(client)
    validate_snapshot_payload(payload)  # Collector 产出合法

    # 薄集成：直接交给 SnapshotStore 持久化（不重构 SnapshotStore）
    store = SnapshotStore(tmp_path / "snapshots")
    record = store.create_snapshot(
        snapshot_id="snap-001",
        instance_id="DEV",
        model_name="Finance",
        payload=payload,
    )
    assert record.snapshot_id == "snap-001"

    # 读回后内容一致
    _, loaded = store.load_snapshot("snap-001")
    assert loaded == payload


# ---------------------------------------------------------------------------
# 15. Existing regression（全量 pytest 覆盖）
# ---------------------------------------------------------------------------
def test_collected_payload_json_serializable():
    client = FakeClient(processes={"P": _raw_process("P")})
    payload = collect_snapshot(client)
    text = json.dumps(payload, ensure_ascii=False)
    assert text  # 全部是 JSON 原生类型
