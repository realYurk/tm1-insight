"""演示数据生成器：无需连接 TM1，即可生成一套完整的演示元数据。

用途：
    让新用户「下载下来、双击 start.bat」就能看到完整 Web UI 效果，
    不必先配置 TM1 连接、也不必拉取真实元数据。

运行方式：
    python -m tm1_suite.seed_demo            # 生成演示数据（覆盖写入 data/）
    python -m tm1_suite.seed_demo --clean    # 删除演示数据，恢复空库

生成的是一套自洽的假模型（销售/成本/利润三张 Cube，一条完整数据流），
覆盖 Web UI 的全部视图：Cube 浏览、TI 进程、知识图谱、代码生成、前端审计。
所有数据均为虚构，仅用于演示界面与功能。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from tm1_suite.config import get_settings
from tm1_suite.store.db import Store
from tm1_suite.store.schema import ALL_TABLES


# ======================================================================
# 演示模型定义（自洽的「销售 → 成本 → 利润」数据流）
# ======================================================================

# 维度：名称 -> 元素列表
_DIMENSIONS: dict[str, list[str]] = {
    "Year": ["2024", "2025", "2026"],
    "Month": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "Version": ["Actual", "Budget", "Forecast"],
    "Region": ["North", "South", "East", "West", "Central"],
    "Product": ["Widget", "Gadget", "Gizmo", "Doodad", "Thingamajig"],
    "Customer": ["Alpha Corp", "Beta Ltd", "Gamma Inc", "Delta GmbH"],
    "Account": ["Revenue", "COGS", "Marketing Expense", "SG&A Expense", "Gross Profit", "Net Profit"],
    "Scenario": ["Base", "Upside", "Downside"],
    "Measure": ["Amount", "Units", "Price"],
}

# Cube：名称 -> 维度顺序
_CUBES: dict[str, list[str]] = {
    "Sales Detail": ["Year", "Month", "Version", "Region", "Product", "Customer", "Measure"],
    "Cost Detail": ["Year", "Month", "Version", "Region", "Product", "Account"],
    "Profit Summary": ["Year", "Month", "Version", "Region", "Product", "Scenario", "Account"],
}

# 带有 Rule 的 Cube（用于演示「规则」Tab）
_CUBE_RULES: dict[str, str] = {
    "Profit Summary": (
        "# 利润汇总 = 销售 - 成本\n"
        "['Gross Profit'] = N: DB('Sales Detail', !Year, !Month, !Version, !Region, !Product, 'All Customers', 'Amount') "
        "- DB('Cost Detail', !Year, !Month, !Version, !Region, !Product, 'COGS');\n"
        "['Net Profit'] = N: ['Gross Profit'] - DB('Cost Detail', !Year, !Month, !Version, !Region, !Product, "
        "'Marketing Expense') - DB('Cost Detail', !Year, !Month, !Version, !Region, !Product, 'SG&A Expense');\n"
        "FEEDERS;\n['Gross Profit'] => ['Net Profit'];\n"
    ),
}

# TI 进程：名称 -> 代码段
_PROCESSES: dict[str, dict] = {
    "Load Sales Detail": {
        "datasource": {"type": "csv", "name": "sales_detail.csv"},
        "parameters": [{"name": "pVersion", "prompt": "版本", "value": "Actual"}],
        "prolog": (
            "# PURPOSE: 从销售明细源 Cube 搬运到 Sales Detail\n"
            "# DATA SOURCE:\n"
            "#    Sales Detail\n"
            "cCubTgt = 'Sales Detail';\n"
            "cCubSrc = 'Sales Staging';\n"
            "sVersion = pVersion;\n"
        ),
        "metadata": "",
        "data": (
            "CellPutN(vAmount, cCubTgt, pVersion, vRegion, vProduct, vCustomer, 'Amount');\n"
            "CellPutN(vUnits, cCubTgt, pVersion, vRegion, vProduct, vCustomer, 'Units');\n"
        ),
        "epilog": "",
    },
    "Load Cost Detail": {
        "datasource": {"type": "csv", "name": "cost_detail.csv"},
        "parameters": [{"name": "pVersion", "prompt": "版本", "value": "Actual"}],
        "prolog": (
            "# PURPOSE: 加载成本明细\n"
            "# DATA SOURCE:\n"
            "#    Cost Staging\n"
            "cCubTgt = 'Cost Detail';\n"
            "sVersion = pVersion;\n"
        ),
        "metadata": "",
        "data": (
            "CellPutN(vAmount, cCubTgt, pVersion, vRegion, vProduct, 'COGS');\n"
        ),
        "epilog": "",
    },
    "Calc Profit Summary": {
        "datasource": {"type": "none"},
        "parameters": [{"name": "pVersion", "prompt": "版本", "value": "Actual"}],
        "prolog": (
            "# PURPOSE: 计算利润汇总\n"
            "cCubTgt = 'Profit Summary';\n"
            "cCubSale = 'Sales Detail';\n"
            "cCubCost = 'Cost Detail';\n"
            "sVersion = pVersion;\n"
            "vScenario = 'Base';\n"
        ),
        "metadata": "",
        "data": (
            "vSales = CellGetN(cCubSale, sVersion, vRegion, vProduct, 'All Customers', 'Amount');\n"
            "vCOGS = CellGetN(cCubCost, sVersion, vRegion, vProduct, 'COGS');\n"
            "vGross = vSales - vCOGS;\n"
            "CellPutN(vGross, cCubTgt, sVersion, vRegion, vProduct, vScenario, 'Gross Profit');\n"
            "vNet = vGross - CellGetN(cCubCost, sVersion, vRegion, vProduct, 'Marketing Expense');\n"
            "CellPutN(vNet, cCubTgt, sVersion, vRegion, vProduct, vScenario, 'Net Profit');\n"
        ),
        "epilog": "ExecuteProcess('Refresh Reports');\n",
    },
    "Refresh Reports": {
        "datasource": {"type": "none"},
        "parameters": [],
        "prolog": "# PURPOSE: 刷新报表缓存\ncCubTgt = 'Profit Summary';\n",
        "metadata": "",
        "data": "CubeClearData(cCubTgt);\n",
        "epilog": "",
    },
    "Maintain Product Dim": {
        "datasource": {"type": "none"},
        "parameters": [{"name": "pProduct", "prompt": "产品", "value": "Widget"}],
        "prolog": "# PURPOSE: 维护产品维度元素\n",
        "metadata": "DimensionElementInsert('Product', '', pProduct, 'N');\n",
        "data": "",
        "epilog": "",
    },
}

# Chore：名称 -> 步骤（process 列表）
_CHORES: dict[str, list[str]] = {
    "Nightly Data Load": ["Load Sales Detail", "Load Cost Detail", "Calc Profit Summary"],
    "Refresh Reports Only": ["Refresh Reports"],
}

# 前端审计资产（Excel 页面 -> 后端 Cube）
_AUDIT_ASSETS: list[dict] = [
    {"menu": "销售分析", "blob_name": "sales_dashboard.xlsx", "asset_type": "excel",
     "risk": "中", "link_status": "正常", "excel_path": "applications/sales_dashboard.xlsx",
     "has_tm1": True, "formula_count": 42},
    {"menu": "成本分析", "blob_name": "cost_report.xlsx", "asset_type": "excel",
     "risk": "低", "link_status": "正常", "excel_path": "applications/cost_report.xlsx",
     "has_tm1": True, "formula_count": 18},
    {"menu": "利润看板", "blob_name": "profit_board.xlsx", "asset_type": "excel",
     "risk": "高", "link_status": "断链", "excel_path": "applications/profit_board.xlsx",
     "has_tm1": True, "formula_count": 67},
    {"menu": "预算录入", "blob_name": "budget_input.xlsx", "asset_type": "excel",
     "risk": "低", "link_status": "正常", "excel_path": "externals/budget_input.xlsx",
     "has_tm1": False, "formula_count": 0},
]

_AUDIT_MAPPINGS: list[dict] = [
    {"menu": "销售分析", "excel_file": "sales_dashboard.xlsx",
     "backend_cubes": "Sales Detail, Profit Summary"},
    {"menu": "成本分析", "excel_file": "cost_report.xlsx",
     "backend_cubes": "Cost Detail"},
    {"menu": "利润看板", "excel_file": "profit_board.xlsx",
     "backend_cubes": "Profit Summary"},
    {"menu": "预算录入", "excel_file": "budget_input.xlsx",
     "backend_cubes": "Sales Detail, Cost Detail"},
]


def _clean(settings) -> None:
    """删除演示数据目录，恢复空库状态。"""
    data_dir = settings.data_dir
    if data_dir.exists():
        shutil.rmtree(data_dir)
    print(f"已删除演示数据目录: {data_dir}")
    print("下次启动 Web UI 将看到空库。")


def seed(settings) -> None:
    """生成演示数据并写入 DuckDB。"""
    store = Store(settings)
    store.init_schema(drop=True)
    con = store.connect()

    try:
        # ---- 维度 ----
        for dim, elements in _DIMENSIONS.items():
            con.execute(
                "INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?, ?)",
                [dim, False, len(elements),
                 json.dumps([{"name": e} for e in elements], ensure_ascii=False),
                 "[]", "[]", "[]"],
            )

        # ---- Cube ----
        for cube, dims in _CUBES.items():
            rules = _CUBE_RULES.get(cube, "")
            con.execute(
                "INSERT INTO cubes VALUES (?, ?, ?, ?, ?)",
                [cube, json.dumps(dims, ensure_ascii=False), rules,
                 bool(rules), len(dims)],
            )
            for i, d in enumerate(dims):
                con.execute(
                    "INSERT INTO cube_has_dimension VALUES (?, ?, ?)", [cube, d, i],
                )

        # ---- Rule 引用 ----
        con.execute(
            "INSERT INTO rule_references_cube VALUES (?, ?)",
            ["Profit Summary", "Sales Detail"],
        )
        con.execute(
            "INSERT INTO rule_references_cube VALUES (?, ?)",
            ["Profit Summary", "Cost Detail"],
        )

        # ---- 进程 ----
        for name, p in _PROCESSES.items():
            prolog = p.get("prolog", "")
            metadata = p.get("metadata", "")
            data = p.get("data", "")
            epilog = p.get("epilog", "")
            full = "\n".join([prolog, metadata, data, epilog])
            con.execute(
                "INSERT INTO processes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [name, prolog, metadata, data, epilog,
                 json.dumps(p.get("parameters", []), ensure_ascii=False),
                 json.dumps(p.get("datasource"), ensure_ascii=False),
                 len(full)],
            )

        # ---- 进程读写关系 ----
        _reads = {
            "Load Sales Detail": ["Sales Staging"],
            "Load Cost Detail": ["Cost Staging"],
            "Calc Profit Summary": ["Sales Detail", "Cost Detail"],
            "Refresh Reports": [],
        }
        _writes = {
            "Load Sales Detail": ["Sales Detail"],
            "Load Cost Detail": ["Cost Detail"],
            "Calc Profit Summary": ["Profit Summary"],
            "Refresh Reports": ["Profit Summary"],
        }
        # 补两个 Staging Cube，让「数据从哪来」流向图更完整
        for staging in ("Sales Staging", "Cost Staging"):
            con.execute(
                "INSERT INTO cubes VALUES (?, ?, ?, ?, ?)",
                [staging, json.dumps(["Year", "Month", "Version", "Region", "Product", "Measure"]),
                 "", False, 6],
            )
        for proc, cubes in _reads.items():
            for c in cubes:
                con.execute("INSERT INTO process_reads_cube VALUES (?, ?)", [proc, c])
        for proc, cubes in _writes.items():
            for c in cubes:
                con.execute("INSERT INTO process_writes_cube VALUES (?, ?)", [proc, c])

        # ---- 进程调用关系 ----
        con.execute(
            "INSERT INTO process_calls_process VALUES (?, ?)",
            ["Calc Profit Summary", "Refresh Reports"],
        )

        # ---- 维度维护 ----
        con.execute(
            "INSERT INTO process_maintains_dimension VALUES (?, ?)",
            ["Maintain Product Dim", "Product"],
        )

        # ---- 血缘层（ti_summary / ti_flows / ti_flow_dims）----
        # 手工构造，演示「谁写入 Cube 的哪个切面」
        flows = [
            ("Load Sales Detail", "Sales Detail", ["Sales Staging"],
             [{"op": "CellPutN", "dims": [
                 {"expr": "pVersion", "value": "<pVersion>"},
                 {"expr": "vRegion", "value": "<vRegion>"},
                 {"expr": "vProduct", "value": "<vProduct>"},
                 {"expr": "'All Customers'", "value": "All Customers"},
                 {"expr": "'Amount'", "value": "Amount"},
             ]}]),
            ("Calc Profit Summary", "Profit Summary", ["Sales Detail", "Cost Detail"],
             [{"op": "CellPutN", "dims": [
                 {"expr": "sVersion", "value": "<sVersion>"},
                 {"expr": "vRegion", "value": "<vRegion>"},
                 {"expr": "vProduct", "value": "<vProduct>"},
                 {"expr": "'Base'", "value": "Base"},
                 {"expr": "'Gross Profit'", "value": "Gross Profit"},
             ]},
              {"op": "CellPutN", "dims": [
                 {"expr": "sVersion", "value": "<sVersion>"},
                 {"expr": "vRegion", "value": "<vRegion>"},
                 {"expr": "vProduct", "value": "<vProduct>"},
                 {"expr": "'Base'", "value": "Base"},
                 {"expr": "'Net Profit'", "value": "Net Profit"},
             ]}]),
        ]
        for proc, target, sources, wps in flows:
            con.execute(
                "INSERT INTO ti_summary VALUES (?, ?, ?, ?, ?, ?)",
                [proc, "[]", len(sources), 1, 0, True],
            )
            con.execute(
                "INSERT INTO ti_flows VALUES (?, ?, ?, ?)",
                [proc, target, json.dumps(sources, ensure_ascii=False), len(wps)],
            )
            for wi, wp in enumerate(wps):
                wp_id = f"{proc}::{target}::{wi}"
                for i, d in enumerate(wp["dims"]):
                    con.execute(
                        "INSERT INTO ti_flow_dims VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [proc, target, wp_id, wp["op"], i, d["expr"], d["value"], "[]"],
                    )

        # ---- Chore ----
        for chore, steps in _CHORES.items():
            con.execute(
                "INSERT INTO chores VALUES (?, ?, ?)",
                [chore, json.dumps([{"name": s, "step_order": i}
                                    for i, s in enumerate(steps)], ensure_ascii=False),
                 len(steps)],
            )
            for i, s in enumerate(steps):
                con.execute(
                    "INSERT INTO chore_runs_process VALUES (?, ?, ?)", [chore, s, i],
                )

        # ---- 审计 ----
        for a in _AUDIT_ASSETS:
            con.execute(
                "INSERT INTO excel_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [a["menu"], a["blob_name"], a["asset_type"], a["risk"], a["link_status"],
                 a["excel_path"], a["has_tm1"], a["formula_count"]],
            )
        for m in _AUDIT_MAPPINGS:
            con.execute(
                "INSERT INTO front_backend_mapping VALUES (?, ?, ?, ?)",
                [m["menu"], m["excel_file"], m["backend_cubes"],
                 len([c for c in m["backend_cubes"].split(",") if c])],
            )

    finally:
        con.close()

    stats = store.all_rows()
    print("演示数据已生成：")
    for t, n in stats.items():
        if n:
            print(f"  {t:32s}: {n}")


def main() -> None:
    settings = get_settings()
    if "--clean" in sys.argv:
        _clean(settings)
        return
    seed(settings)


if __name__ == "__main__":
    main()
