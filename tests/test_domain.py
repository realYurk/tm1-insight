"""Domain Model（domain/）的回归测试。

验证：
1. Model / Instance / Snapshot 概念可表达
2. Cube / Dimension / Hierarchy / Process / Chore / Rule 可表达
3. Reference 与 Dependency 是**不同对象**，关系正确
4. 对象基本关系正确（Instance → Model → Snapshot → 对象）
5. Domain Model **不依赖 DuckDB / API / parser / resolver**（纯 Python 语义层）

测试数据均为最小匿名 fixture，不触碰任何生产数据 / 数据库 / 服务器。
"""
from __future__ import annotations

import dataclasses

from tm1_insight.domain import (
    Application,
    Change,
    Chore,
    Cube,
    Dependency,
    DependencyKind,
    Dimension,
    Element,
    Feeder,
    HealthFinding,
    Hierarchy,
    Impact,
    Instance,
    Lineage,
    Model,
    Process,
    Reference,
    ReferenceKind,
    Rule,
    Snapshot,
    Subset,
    Workbook,
    Worksheet,
)


# ---------------------------------------------------------------------------
# 1~3. Instance / Model / Snapshot 概念关系
# ---------------------------------------------------------------------------
def test_instance_model_snapshot_hierarchy():
    inst = Instance(name="PA-Prod")
    model = Model(name="Finance", instance=inst)
    snap = Snapshot(model=model, snapshot_id="20261011-160000", created_at="2026-10-11T16:00:00")

    assert inst.name == "PA-Prod"
    assert model.name == "Finance"
    assert model.instance is inst
    assert snap.model is model
    assert snap.snapshot_id == "20261011-160000"
    assert snap.source == "tm1"


def test_snapshot_is_immutable():
    snap = Snapshot(model=Model(name="M"), snapshot_id="s1")

    # 冻结 dataclass：对字段赋值应抛 FrozenInstanceError
    try:
        snap.snapshot_id = "s2"
        assert False, "Snapshot 应是不可变的"
    except dataclasses.FrozenInstanceError:
        pass


def test_snapshot_object_counts():
    snap = Snapshot(
        model=Model(name="M"),
        snapshot_id="s1",
        object_counts={"cubes": 5, "processes": 12, "dimensions": 9},
    )
    assert snap.object_counts["cubes"] == 5
    assert snap.object_counts["processes"] == 12


# ---------------------------------------------------------------------------
# 4~6. Cube / Dimension / Hierarchy / Process / Chore / Rule
# ---------------------------------------------------------------------------
def test_cube_with_dimensions_and_rules():
    cube = Cube(name="Sales", dimensions=("Year", "Month", "Product", "Measure"), rules=("['Gross']=N:...;",))
    assert cube.name == "Sales"
    assert cube.dimensions == ("Year", "Month", "Product", "Measure")
    assert len(cube.rules) == 1


def test_dimension_with_elements_and_subsets():
    dim = Dimension(name="Product", elements=("P1", "P2", "Total Product"), subsets=("All Products",))
    assert dim.name == "Product"
    assert "P1" in dim.elements
    assert "All Products" in dim.subsets


def test_hierarchy_element_subset():
    hier = Hierarchy(name="Product", dimension="Product", elements=("P1", "P2"))
    elem = Element(name="P1", hierarchy="Product", parent="Total Product")
    sub = Subset(name="All Products", dimension="Product", elements=("P1", "P2"))

    assert hier.dimension == "Product"
    assert elem.parent == "Total Product"
    assert sub.dimension == "Product"
    assert sub.elements == ("P1", "P2")


def test_process_with_parameters():
    proc = Process(name="Load Sales", code="vCube='Sales';", parameters=("pYear", "pMonth"))
    assert proc.name == "Load Sales"
    assert proc.parameters == ("pYear", "pMonth")


def test_chore_runs_processes():
    chore = Chore(name="Nightly Load", processes=("Load Sales", "Load Cost"))
    assert chore.processes == ("Load Sales", "Load Cost")


def test_rule_and_feeder():
    rule = Rule(cube="Sales", statement="['Gross']=N:...;", referenced_cubes=("Cost",))
    feeder = Feeder(cube="Sales", statement="['Cost']=>['Gross'];")

    assert rule.cube == "Sales"
    assert rule.referenced_cubes == ("Cost",)
    assert feeder.cube == "Sales"


# ---------------------------------------------------------------------------
# 7~9. Reference 与 Dependency 的区分与关系
# ---------------------------------------------------------------------------
def test_reference_is_syntax_fact():
    ref = Reference(
        kind=ReferenceKind.CELL_PUT,
        source="Load Sales",
        target="Sales",
        operation="CellPutN",
        evidence={"snapshot_id": "s1", "line": 12},
    )
    assert ref.kind == ReferenceKind.CELL_PUT
    assert ref.source == "Load Sales"
    assert ref.target == "Sales"
    assert ref.snapshot_id == "s1"
    assert ref.evidence["line"] == 12


def test_dependency_is_semantic_conclusion():
    ref = Reference(
        kind=ReferenceKind.CELL_PUT,
        source="Load Sales",
        target="Sales",
        operation="CellPutN",
        evidence={"snapshot_id": "s1"},
    )
    dep = Dependency(
        kind=DependencyKind.PROCESS_WRITES_CUBE,
        source="Load Sales",
        target="Sales",
        references=(ref,),
        confidence=0.95,
    )
    assert dep.kind == DependencyKind.PROCESS_WRITES_CUBE
    assert dep.source == "Load Sales"
    assert dep.target == "Sales"
    assert dep.references == (ref,)
    assert dep.confidence == 0.95


def test_reference_and_dependency_are_distinct_types():
    ref = Reference(kind=ReferenceKind.CELL_GET, source="P", target="Cube")
    dep = Dependency(kind=DependencyKind.PROCESS_READS_CUBE, source="P", target="Cube")

    # 两者是不同类型，且 Reference 不携带语义方向、Dependency 携带
    assert type(ref) is not type(dep)
    assert not hasattr(ref, "confidence")
    assert hasattr(dep, "confidence")


def test_process_call_dependency_kind():
    dep = Dependency(
        kind=DependencyKind.PROCESS_CALLS_PROCESS,
        source="P_Master",
        target="P_Child",
    )
    assert dep.kind == DependencyKind.PROCESS_CALLS_PROCESS
    assert dep.source == "P_Master"
    assert dep.target == "P_Child"


# ---------------------------------------------------------------------------
# 轻量定义与概念占位对象
# ---------------------------------------------------------------------------
def test_frontend_assets():
    ws = Worksheet(name="Sheet1")
    wb = Workbook(name="Report.xlsx", worksheets=(ws,))
    app = Application(name="Finance Reports", workbooks=(wb,))

    assert app.name == "Finance Reports"
    assert app.workbooks[0].name == "Report.xlsx"
    assert app.workbooks[0].worksheets[0].name == "Sheet1"


def test_lineage_concept_only():
    dep = Dependency(kind=DependencyKind.PROCESS_WRITES_CUBE, source="P", target="Sales")
    lin = Lineage(target="Sales", dependencies=(dep,), upstream=("P",), downstream=("Report.xlsx",))

    assert lin.target == "Sales"
    assert lin.dependencies == (dep,)
    assert "P" in lin.upstream
    assert "Report.xlsx" in lin.downstream


def test_change_impact_health_placeholders():
    chg = Change(object_name="P_Load", change_type="changed")
    imp = Impact(source="Cube_X", affected=("Cube_Y", "P_C"), kind="indirect")
    hf = HealthFinding(finding="Orphan process", severity="medium", affected_objects=("P_X",))

    assert chg.change_type == "changed"
    assert imp.kind == "indirect"
    assert hf.severity == "medium"


# ---------------------------------------------------------------------------
# 10. Domain Model 不依赖 DuckDB / 引擎层
# ---------------------------------------------------------------------------
def test_domain_model_has_no_duckdb_dependency():
    import ast
    import tm1_insight.domain.model as dm

    with open(dm.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    # 领域层不得 import duckdb / fastapi / 引擎内部模块（精确检查 import 语句，非全文）
    forbidden = {"duckdb", "fastapi", "sqlalchemy", "pydantic"}
    forbidden_modules = {"tm1_insight.ingest", "tm1_insight.store", "tm1_insight.api"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden, \
                    f"domain/model.py 不应 import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden, \
                f"domain/model.py 不应 from {mod} import"
            assert not mod.startswith("tm1_insight.ingest"), \
                "domain/model.py 不应依赖 tm1_insight.ingest"
            assert not mod.startswith("tm1_insight.store"), \
                "domain/model.py 不应依赖 tm1_insight.store"
            assert not mod.startswith("tm1_insight.api"), \
                "domain/model.py 不应依赖 tm1_insight.api"


def test_domain_all_exports_available():
    import tm1_insight.domain as d

    for name in (
        "Instance", "Model", "Snapshot", "Cube", "Dimension", "Hierarchy",
        "Element", "Subset", "Process", "Chore", "Rule", "Feeder",
        "Application", "Workbook", "Worksheet", "Reference", "Dependency",
        "Lineage", "Change", "Impact", "HealthFinding",
    ):
        assert hasattr(d, name), f"domain 包应导出 {name}"
