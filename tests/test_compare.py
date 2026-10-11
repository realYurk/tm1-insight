"""Snapshot Compare Engine v1（compare/）的测试。

覆盖（对应 Task 15 要求）：
1.  empty vs empty
2.  all objects added
3.  all objects removed
4.  unchanged
5.  process modified
6.  cube modified
7.  dimension modified
8.  rule modified / identity handling
9.  mixed added/removed/modified/unchanged
10. deterministic ordering
11. reversed input collections
12. duplicate identity
13. schema version mismatch
14. before snapshot ID preserved
15. after snapshot ID preserved
16. content hash does not replace object compare
17. before/after evidence
18. no snapshot mutation
19. no Graph DB dependency
20. no AI dependency
21. no TI re-parsing
22. regression Task 1~14

所有测试走真实链路，不 mock 引擎。核心：对象级、确定性、可解释、不可变、可复现。
"""
from __future__ import annotations

from tm1_insight.compare import (
    CompareEngine,
    CompareError,
    compare_payloads,
    compare_snapshots,
)
from tm1_insight.domain.model import ChangeKind


def _proc(name, data="CellPutN(1, 'Cube_A', 'd', 'm');"):
    return {"name": name, "prolog": "", "metadata": "", "data": data, "epilog": ""}


def _cube(name, dims=("Dim_A",)):
    return {"name": name, "dimensions": list(dims), "rules": []}


def _dim(name, elements=("E1",)):
    return {"name": name, "elements": list(elements), "subsets": []}


def _rule(cube, statement="['x']=N:1;", refs=("Cube_B",)):
    return {"cube": cube, "statement": statement, "referenced_cubes": list(refs)}


def _payload(**kwargs) -> dict:
    p = {"processes": [], "rules": [], "cubes": [], "dimensions": []}
    p.update(kwargs)
    return p


# ---------------------------------------------------------------------------
# 1. empty vs empty
# ---------------------------------------------------------------------------
def test_empty_vs_empty():
    result = compare_payloads(_payload(), _payload())
    assert result.changes == ()
    assert result.statistics["added_count"] == 0
    assert result.statistics["removed_count"] == 0
    assert result.statistics["modified_count"] == 0
    assert result.statistics["unchanged_count"] == 0


# ---------------------------------------------------------------------------
# 2. all objects added
# ---------------------------------------------------------------------------
def test_all_objects_added():
    before = _payload()
    after = _payload(cubes=[_cube("Cube_A")], dimensions=[_dim("Dim_A")])
    result = compare_payloads(before, after)

    kinds = {c.change_type for c in result.changes}
    assert kinds == {ChangeKind.ADDED.value}
    assert result.statistics["added_count"] == 2


# ---------------------------------------------------------------------------
# 3. all objects removed
# ---------------------------------------------------------------------------
def test_all_objects_removed():
    before = _payload(cubes=[_cube("Cube_A")], dimensions=[_dim("Dim_A")])
    after = _payload()
    result = compare_payloads(before, after)

    kinds = {c.change_type for c in result.changes}
    assert kinds == {ChangeKind.REMOVED.value}
    assert result.statistics["removed_count"] == 2


# ---------------------------------------------------------------------------
# 4. unchanged
# ---------------------------------------------------------------------------
def test_unchanged():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_A")])
    result = compare_payloads(before, after)

    assert result.changes == ()
    assert result.statistics["unchanged_count"] == 1


# ---------------------------------------------------------------------------
# 5. process modified
# ---------------------------------------------------------------------------
def test_process_modified():
    before = _payload(processes=[_proc("Process_A", data="CellPutN(1, 'Cube_A', 'd', 'm');")])
    after = _payload(processes=[_proc("Process_A", data="CellPutN(1, 'Cube_A', 'd', 'm');\nCellPutN(2, 'Cube_B', 'd', 'm');")])
    result = compare_payloads(before, after)

    assert len(result.changes) == 1
    c = result.changes[0]
    assert c.object_type == "process"
    assert c.object_name == "Process_A"
    assert c.change_type == ChangeKind.MODIFIED.value
    # before/after evidence
    assert c.before["data"] == "CellPutN(1, 'Cube_A', 'd', 'm');"
    assert "CellPutN(2, 'Cube_B'" in c.after["data"]


# ---------------------------------------------------------------------------
# 6. cube modified
# ---------------------------------------------------------------------------
def test_cube_modified():
    before = _payload(cubes=[_cube("Cube_A", dims=("Dim_A",))])
    after = _payload(cubes=[_cube("Cube_A", dims=("Dim_A", "Dim_B"))])
    result = compare_payloads(before, after)

    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeKind.MODIFIED.value
    assert result.changes[0].object_type == "cube"


# ---------------------------------------------------------------------------
# 7. dimension modified
# ---------------------------------------------------------------------------
def test_dimension_modified():
    before = _payload(dimensions=[_dim("Dim_A", elements=("E1",))])
    after = _payload(dimensions=[_dim("Dim_A", elements=("E1", "E2"))])
    result = compare_payloads(before, after)

    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeKind.MODIFIED.value
    assert result.changes[0].object_type == "dimension"


# ---------------------------------------------------------------------------
# 8. rule modified / identity handling
# ---------------------------------------------------------------------------
def test_rule_modified_referenced_cubes():
    # 同 cube + 同 statement → 同一 identity，referenced_cubes 变化 → MODIFIED
    before = _payload(rules=[_rule("Cube_A", statement="['x']=N:1;", refs=("Cube_B",))])
    after = _payload(rules=[_rule("Cube_A", statement="['x']=N:1;", refs=("Cube_B", "Cube_C"))])
    result = compare_payloads(before, after)

    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeKind.MODIFIED.value
    assert result.changes[0].object_type == "rule"


def test_rule_statement_change_is_added_removed():
    # Rule 的 identity 是 (cube, statement)，statement 变化 → 旧 REMOVED + 新 ADDED
    before = _payload(rules=[_rule("Cube_A", statement="['x']=N:1;")])
    after = _payload(rules=[_rule("Cube_A", statement="['x']=N:2;")])
    result = compare_payloads(before, after)

    kinds = sorted(c.change_type for c in result.changes)
    assert kinds == [ChangeKind.ADDED.value, ChangeKind.REMOVED.value]


# ---------------------------------------------------------------------------
# 9. mixed added/removed/modified/unchanged
# ---------------------------------------------------------------------------
def test_mixed_changes():
    before = _payload(
        cubes=[_cube("Cube_A"), _cube("Cube_B")],          # A unchanged, B removed
        dimensions=[_dim("Dim_A")],                         # Dim_A modified
        processes=[_proc("P_A")],                           # P_A removed
    )
    after = _payload(
        cubes=[_cube("Cube_A"), _cube("Cube_C")],          # C added
        dimensions=[_dim("Dim_A", elements=("E1", "E2"))],  # Dim_A modified
        processes=[_proc("P_B")],                           # P_B added
    )
    result = compare_payloads(before, after)

    stats = result.statistics
    assert stats["added_count"] == 2      # Cube_C + P_B
    assert stats["removed_count"] == 2    # Cube_B + P_A
    assert stats["modified_count"] == 1   # Dim_A
    assert stats["unchanged_count"] == 1  # Cube_A


# ---------------------------------------------------------------------------
# 10. deterministic ordering
# ---------------------------------------------------------------------------
def test_deterministic_ordering():
    before = _payload(cubes=[_cube("Cube_Z"), _cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B"), _cube("Cube_M")])
    result = compare_payloads(before, after)

    # 稳定排序：object_type → identity → change_type
    keys = [(c.object_type, c.object_name, c.change_type) for c in result.changes]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# 11. reversed input collections（正反序结果一致）
# ---------------------------------------------------------------------------
def test_reversed_input_collections():
    before_forward = _payload(cubes=[_cube("Cube_A"), _cube("Cube_B")])
    before_reverse = _payload(cubes=[_cube("Cube_B"), _cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_C")])

    r1 = compare_payloads(before_forward, after)
    r2 = compare_payloads(before_reverse, after)

    assert [(c.object_name, c.change_type) for c in r1.changes] == \
        [(c.object_name, c.change_type) for c in r2.changes]


# ---------------------------------------------------------------------------
# 12. duplicate identity（明确失败，不静默覆盖）
# ---------------------------------------------------------------------------
def test_duplicate_identity_raises():
    before = _payload(cubes=[_cube("Cube_A"), _cube("Cube_A")])
    after = _payload()
    try:
        compare_payloads(before, after)
        assert False, "应抛出 CompareError"
    except CompareError:
        pass


# ---------------------------------------------------------------------------
# 13. schema version mismatch（Task 15.1 Contract Hardening）
# ---------------------------------------------------------------------------
def test_schema_version_mismatch():
    # 两个 Snapshot 都明确携带 schema_version 且不同 → CompareError，绝不静默比较
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_A")])
    before["schema_version"] = 1
    after["schema_version"] = 2

    try:
        compare_snapshots(before, after)
        assert False, "应抛出 CompareError"
    except CompareError as e:
        msg = str(e)
        assert "1" in msg and "2" in msg


def test_schema_version_same_succeeds():
    # 两个 Snapshot 携带相同 schema_version → 正常 compare
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    before["schema_version"] = 1
    after["schema_version"] = 1

    result = compare_snapshots(before, after)
    assert result.statistics["removed_count"] == 1
    assert result.statistics["added_count"] == 1


def test_schema_version_mismatch_reversed_input():
    # 反转 before/after 不影响 schema 校验结果（都应为 CompareError）
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_A")])
    before["schema_version"] = 2
    after["schema_version"] = 1

    try:
        compare_snapshots(before, after)
        assert False, "应抛出 CompareError"
    except CompareError:
        pass

    # 对称：换一种赋值方式也一致
    b2 = _payload(cubes=[_cube("Cube_A")])
    a2 = _payload(cubes=[_cube("Cube_A")])
    b2["schema_version"] = 1
    a2["schema_version"] = 2
    try:
        compare_snapshots(a2, b2)
        assert False, "应抛出 CompareError"
    except CompareError:
        pass


def test_schema_version_record_object():
    # 携带 .schema_version 属性的对象（如 SnapshotRecord）也能校验
    from tm1_insight.snapshot import SnapshotRecord

    before_rec = SnapshotRecord(
        snapshot_id="s1", instance_id="DEV", model_name="M", schema_version=1
    )
    after_rec = SnapshotRecord(
        snapshot_id="s2", instance_id="DEV", model_name="M", schema_version=2
    )

    try:
        compare_snapshots(before_rec, after_rec)
        assert False, "应抛出 CompareError"
    except CompareError as e:
        assert "1" in str(e) and "2" in str(e)


# ---------------------------------------------------------------------------
# 14/15. before/after snapshot ID preserved
# ---------------------------------------------------------------------------
def test_snapshot_ids_preserved():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    result = compare_payloads(before, after, before_snapshot_id="snap-1", after_snapshot_id="snap-2")

    assert result.before_snapshot_id == "snap-1"
    assert result.after_snapshot_id == "snap-2"


# ---------------------------------------------------------------------------
# 16. content hash does not replace object compare
# ---------------------------------------------------------------------------
def test_content_hash_does_not_replace_object_compare():
    # 字段顺序不同但内容相同 → 对象级 compare 判定 unchanged（不是靠 hash 判定 changed）
    before = _payload(cubes=[{"name": "Cube_A", "dimensions": ["D1", "D2"], "rules": []}])
    after = _payload(cubes=[{"rules": [], "dimensions": ["D1", "D2"], "name": "Cube_A"}])

    result = compare_payloads(before, after)
    assert result.changes == ()  # canonical compare：字段顺序无关
    assert result.statistics["unchanged_count"] == 1

    # 真正变化时才 MODIFIED
    after2 = _payload(cubes=[{"name": "Cube_A", "dimensions": ["D1", "D3"], "rules": []}])
    result2 = compare_payloads(before, after2)
    assert result2.statistics["modified_count"] == 1


# ---------------------------------------------------------------------------
# 17. before/after evidence
# ---------------------------------------------------------------------------
def test_before_after_evidence():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    result = compare_payloads(before, after)

    # added 的 before 为 None，after 有对象
    added = [c for c in result.changes if c.change_type == ChangeKind.ADDED.value][0]
    assert added.before is None
    assert added.after["name"] == "Cube_B"

    removed = [c for c in result.changes if c.change_type == ChangeKind.REMOVED.value][0]
    assert removed.before["name"] == "Cube_A"
    assert removed.after is None


# ---------------------------------------------------------------------------
# 18. no snapshot mutation
# ---------------------------------------------------------------------------
def test_no_snapshot_mutation():
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    before_copy = _payload(cubes=[_cube("Cube_A")])
    after_copy = _payload(cubes=[_cube("Cube_B")])

    compare_payloads(before, after)

    # 输入 payload 未被修改
    assert before == before_copy
    assert after == after_copy


# ---------------------------------------------------------------------------
# 19. no Graph DB dependency
# ---------------------------------------------------------------------------
def test_compare_module_has_no_forbidden_dependency():
    import ast
    import tm1_insight.compare.engine as ce

    with open(ce.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"duckdb", "fastapi", "sqlalchemy", "networkx", "neo4j"}
    forbidden_modules = {"tm1_insight.ingest", "tm1_insight.store", "tm1_insight.api",
                         "tm1_insight.parser", "tm1_insight.resolver", "tm1_insight.dependency",
                         "tm1_insight.lineage", "tm1_insight.impact", "tm1_insight.health"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden
            assert not mod.startswith("tm1_insight.ingest"), "compare 不应依赖 ingest"
            assert not mod.startswith("tm1_insight.dependency"), "compare 不应依赖 dependency"


# ---------------------------------------------------------------------------
# 20. no AI dependency
# ---------------------------------------------------------------------------
def test_compare_module_has_no_ai_dependency():
    import ast
    import tm1_insight.compare.engine as ce

    with open(ce.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"openai", "anthropic", "llm", "langchain", "transformers",
                 "torch", "tensorflow", "rag", "embedding", "vectorstore"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden


# ---------------------------------------------------------------------------
# 21. no TI re-parsing（compare 不依赖 parser/resolver）
# ---------------------------------------------------------------------------
def test_compare_no_ti_reparsing():
    import ast
    import tm1_insight.compare.engine as ce

    with open(ce.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("tm1_insight.parser"), "compare 不应重新解析 TI"
            assert not mod.startswith("tm1_insight.resolver"), "compare 不应重新 resolve"


# ---------------------------------------------------------------------------
# 附加：CompareEngine 类 API + compare_snapshots 便捷函数
# ---------------------------------------------------------------------------
def test_compare_engine_class_api():
    engine = CompareEngine()
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    result = engine.compare(before, after)
    assert len(result.changes) == 2  # removed A + added B


def test_compare_snapshots_alias():
    # 无 schema_version 的纯 payload → compare_snapshots 退化回 payload-only（向后兼容）
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    r1 = compare_snapshots(before, after)
    r2 = compare_payloads(before, after)
    assert [(c.object_name, c.change_type) for c in r1.changes] == \
        [(c.object_name, c.change_type) for c in r2.changes]


# ---------------------------------------------------------------------------
# Task 15.1 附加：payload-only 向后兼容 + schema_version 单向缺失降级
# ---------------------------------------------------------------------------
def test_payload_only_compare_remains_backward_compatible():
    # payload-only compare（无 schema_version）必须继续工作，不抛错
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    result = compare_payloads(before, after)
    assert result.statistics["removed_count"] == 1
    assert result.statistics["added_count"] == 1


def test_schema_version_one_side_missing_degrades_to_payload_only():
    # 只有一侧携带 schema_version → 不校验（payload-only 无法得知版本），继续比较
    before = _payload(cubes=[_cube("Cube_A")])
    after = _payload(cubes=[_cube("Cube_B")])
    after["schema_version"] = 1  # 仅 after 有版本

    result = compare_snapshots(before, after)
    assert result.statistics["removed_count"] == 1
    assert result.statistics["added_count"] == 1
