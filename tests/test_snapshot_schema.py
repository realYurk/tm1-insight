"""Snapshot Model Object Schema（snapshot/schema.py）的回归测试。

覆盖（对应 Task 8 要求）：
1.  合法最小 Process payload
2.  完整 Process（parameters/prolog/metadata/data/epilog）
3.  非法 Process（name 缺失）
4.  非法 Process（data 非 string）
5.  Rule payload
6.  Cube payload
7.  Dimension payload
8.  完整 Snapshot payload（processes/rules/cubes/dimensions）
9.  未知额外字段（forward-compatible，默认允许）
10. JSON round trip（json.dumps → json.loads → validate）
11. Python 类型污染检查（无 Enum/tuple/dataclass/Path/datetime）
12. Schema version（当前 version=1 行为）
13. 旧 Snapshot 兼容（Task 1~7 测试仍通过，由全量 pytest 保证）

测试只使用最小 fixture，不连接 TM1 Server、不扫描真实 DuckDB。
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import json
from pathlib import Path

import pytest

from tm1_suite.domain.model import Cube, Dimension, Process, Rule
from tm1_suite.snapshot import (
    SnapshotSchemaError,
    SUPPORTED_SCHEMA_VERSION,
    cube_to_payload,
    dimension_to_payload,
    process_to_payload,
    rule_to_payload,
    to_payload_dict,
    validate_snapshot_payload,
)


# ---------------------------------------------------------------------------
# 1. 合法最小 Process
# ---------------------------------------------------------------------------
def test_minimal_process_payload_valid():
    payload = {"name": "Process_A", "prolog": "", "metadata": "", "data": "", "epilog": ""}
    validate_snapshot_payload({"processes": [payload]})  # 不抛异常


# ---------------------------------------------------------------------------
# 2. 完整 Process
# ---------------------------------------------------------------------------
def test_full_process_payload_valid():
    payload = {
        "name": "Process_A",
        "parameters": [{"name": "pCube"}, {"name": "pVersion"}],
        "prolog": "vCube = 'Cube_A';",
        "metadata": "",
        "data": "CellPutN(1, vCube, '2024', 'Measure');",
        "epilog": "",
    }
    validate_snapshot_payload({"processes": [payload]})


# ---------------------------------------------------------------------------
# 3. 非法 Process：name 缺失
# ---------------------------------------------------------------------------
def test_process_missing_name_fails():
    payload = {"data": "CellPutN(1, 'Cube_A', 'd', 'm');"}
    with pytest.raises(SnapshotSchemaError):
        validate_snapshot_payload({"processes": [payload]})


# ---------------------------------------------------------------------------
# 4. 非法 Process：data 非 string
# ---------------------------------------------------------------------------
def test_process_non_string_data_fails():
    payload = {"name": "P", "data": 123}
    with pytest.raises(SnapshotSchemaError):
        validate_snapshot_payload({"processes": [payload]})


def test_process_non_string_parameter_name_fails():
    payload = {"name": "P", "parameters": [{"name": 123}]}
    with pytest.raises(SnapshotSchemaError):
        validate_snapshot_payload({"processes": [payload]})


# ---------------------------------------------------------------------------
# 5. Rule payload
# ---------------------------------------------------------------------------
def test_rule_payload_valid():
    payload = {"cube": "Cube_A", "statement": "...", "referenced_cubes": ["Cube_B"]}
    validate_snapshot_payload({"rules": [payload]})


def test_rule_non_string_referenced_cube_fails():
    payload = {"cube": "Cube_A", "referenced_cubes": [1]}
    with pytest.raises(SnapshotSchemaError):
        validate_snapshot_payload({"rules": [payload]})


# ---------------------------------------------------------------------------
# 6. Cube payload
# ---------------------------------------------------------------------------
def test_cube_payload_valid():
    payload = {"name": "Cube_A", "dimensions": ["Dim_A", "Dim_B"]}
    validate_snapshot_payload({"cubes": [payload]})


# ---------------------------------------------------------------------------
# 7. Dimension payload
# ---------------------------------------------------------------------------
def test_dimension_payload_valid():
    payload = {"name": "Dim_A", "elements": ["E1", "E2"], "subsets": ["All"]}
    validate_snapshot_payload({"dimensions": [payload]})


# ---------------------------------------------------------------------------
# 8. 完整 Snapshot payload
# ---------------------------------------------------------------------------
def test_full_snapshot_payload_valid():
    payload = {
        "processes": [
            {"name": "P_Load", "parameters": [{"name": "pYear"}], "data": "..."},
        ],
        "rules": [{"cube": "Cube_A", "referenced_cubes": ["Cube_B"]}],
        "cubes": [{"name": "Cube_A", "dimensions": ["Dim_A"]}],
        "dimensions": [{"name": "Dim_A", "elements": ["E1"]}],
    }
    validate_snapshot_payload(payload)


# ---------------------------------------------------------------------------
# 9. 未知额外字段（forward-compatible）
# ---------------------------------------------------------------------------
def test_unknown_extra_fields_allowed():
    payload = {
        "processes": [{"name": "P", "data": "...", "some_future_field": True}],
        "applications": [{"name": "App1"}],  # 未来对象，validator 不禁止
    }
    # 额外字段不导致失败
    validate_snapshot_payload(payload)


# ---------------------------------------------------------------------------
# 10. JSON round trip
# ---------------------------------------------------------------------------
def test_json_round_trip():
    payload = {
        "processes": [{"name": "P", "parameters": [{"name": "pYear"}], "data": "..."}],
        "rules": [{"cube": "A", "referenced_cubes": ["B"]}],
    }
    text = json.dumps(payload, ensure_ascii=False)
    reloaded = json.loads(text)
    validate_snapshot_payload(reloaded)  # 不抛异常


# ---------------------------------------------------------------------------
# 11. Python 类型污染检查
# ---------------------------------------------------------------------------
def test_no_python_specific_types_in_serialized_payload():
    proc = Process(name="P", code="CellPutN(1, 'Cube_A', 'd', 'm');", parameters=("pYear",))
    rule = Rule(cube="Cube_A", referenced_cubes=("Cube_B",))
    cube = Cube(name="Cube_A", dimensions=("Dim_A", "Dim_B"))
    dim = Dimension(name="Dim_A", elements=("E1",), subsets=("All",))

    payload = to_payload_dict(
        processes=[proc], rules=[rule], cubes=[cube], dimensions=[dim]
    )
    text = json.dumps(payload, ensure_ascii=False)
    # json.dumps 成功 = 全部是 JSON 原生类型；若含 Enum/tuple/dataclass/Path/datetime 会失败
    assert text

    # 显式断言：序列化后无 Python 专属类型
    def walk(v):
        assert not isinstance(v, enum.Enum)
        assert not isinstance(v, tuple)
        assert not dataclasses.is_dataclass(v)
        assert not isinstance(v, Path)
        assert not isinstance(v, (datetime.date, datetime.datetime))
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(json.loads(text))


# ---------------------------------------------------------------------------
# 12. Schema version
# ---------------------------------------------------------------------------
def test_schema_version_is_one():
    assert SUPPORTED_SCHEMA_VERSION == 1


def test_payload_has_no_schema_version():
    # payload 不放置第二份 schema_version（版本在 Metadata/SnapshotRecord 中）
    payload = to_payload_dict(processes=[Process(name="P", code="")])
    assert "schema_version" not in payload


# ---------------------------------------------------------------------------
# 13. 旧 Snapshot 兼容：Task 7 的 Analysis 仍能消费 schema 产物
# ---------------------------------------------------------------------------
def test_schema_output_feeds_analysis():
    # 用 schema 序列化产物再交给 Analysis Assembly，验证链路仍通
    from tm1_suite.analysis import analyze_snapshot

    proc = Process(name="P_Load", code="CellPutN(100, 'Cube_A', '2024', 'Measure');")
    rule = Rule(cube="Cube_X", referenced_cubes=("Cube_A",))
    payload = to_payload_dict(processes=[proc], rules=[rule])

    validate_snapshot_payload(payload)  # schema 合法
    result = analyze_snapshot(payload, snapshot_id="snap")

    # Analysis 仍能正常消费（四段 process 的 data 段）
    assert result.statistics["process_count"] == 1
    assert result.statistics["rule_count"] == 1
    assert len(result.dependencies) == 2


def test_process_to_payload_preserves_code():
    proc = Process(name="P", code="CellPutN(1, 'Cube_A', 'd', 'm');", parameters=("pYear",))
    p = process_to_payload(proc)
    assert p["name"] == "P"
    assert p["data"] == "CellPutN(1, 'Cube_A', 'd', 'm');"
    assert p["parameters"] == [{"name": "pYear"}]
