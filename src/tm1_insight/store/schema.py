"""统一 DuckDB schema。

把原 tm1_graph.duckdb（12 表）与 cell_lineage.duckdb（6 表）合并为单一库，
并补充 audit 层。分层：object → relation → lineage → audit。

说明：
- JSON 字段以 TEXT 存储（json.dumps 字符串），查询时用 DuckDB json 扩展/函数。
- lineage 层原本重复的 `cube_dimensions` 表已并入 relation 层的 `cube_has_dimension`。
"""
from __future__ import annotations

# 对象层：TM1 实体
OBJECT_TABLES: dict[str, str] = {
    "cubes": """
        CREATE TABLE cubes (
            name TEXT PRIMARY KEY,
            dimensions TEXT,
            rules TEXT,
            has_rules BOOLEAN,
            dimension_count INTEGER
        )""",
    "processes": """
        CREATE TABLE processes (
            name TEXT PRIMARY KEY,
            prolog TEXT,
            metadata TEXT,
            data TEXT,
            epilog TEXT,
            parameters TEXT,
            datasource TEXT,
            code_length INTEGER
        )""",
    "dimensions": """
        CREATE TABLE dimensions (
            name TEXT PRIMARY KEY,
            is_system BOOLEAN,
            element_count INTEGER,
            elements TEXT,
            attributes TEXT,
            edges TEXT,
            subsets TEXT
        )""",
    "dimension_metadata": """
        CREATE TABLE IF NOT EXISTS dimension_metadata (
            name TEXT PRIMARY KEY,
            hierarchy_names TEXT,
            hierarchies TEXT,
            subset_definitions TEXT,
            attribute_values TEXT,
            collected_at TEXT
        )""",
    "chores": """
        CREATE TABLE chores (
            name TEXT PRIMARY KEY,
            processes TEXT,
            process_count INTEGER,
            start_time TEXT,
            frequency TEXT,
            execution_mode TEXT,
            active TEXT
        )""",
}

# 关系层：对象间引用/依赖（图查询核心）
RELATION_TABLES: dict[str, str] = {
    "process_reads_cube": "CREATE TABLE process_reads_cube (process_name TEXT, cube_name TEXT)",
    "process_writes_cube": "CREATE TABLE process_writes_cube (process_name TEXT, cube_name TEXT)",
    "process_calls_process": "CREATE TABLE process_calls_process (caller TEXT, callee TEXT)",
    "process_maintains_dimension": "CREATE TABLE process_maintains_dimension (process_name TEXT, dimension_name TEXT)",
    "process_updates_attribute": "CREATE TABLE process_updates_attribute (process_name TEXT, dimension_name TEXT)",
    "cube_has_dimension": "CREATE TABLE cube_has_dimension (cube_name TEXT, dimension_name TEXT, dim_order INTEGER)",
    "rule_references_cube": "CREATE TABLE rule_references_cube (cube_name TEXT, source_cube TEXT)",
    "chore_runs_process": "CREATE TABLE chore_runs_process (chore_name TEXT, process_name TEXT, step_order INTEGER)",
}

# 血缘层：TI 逐语句解析产物（写入点维度 + IF 条件 + 调用）
LINEAGE_TABLES: dict[str, str] = {
    "ti_summary": """
        CREATE TABLE ti_summary (
            name TEXT PRIMARY KEY,
            params TEXT,
            source_cube_count INTEGER,
            target_cube_count INTEGER,
            business_call_count INTEGER,
            has_flow BOOLEAN
        )""",
    "ti_flows": """
        CREATE TABLE ti_flows (
            process_name TEXT,
            target_cube TEXT,
            source_cubes TEXT,
            write_point_count INTEGER
        )""",
    "ti_flow_dims": """
        CREATE TABLE ti_flow_dims (
            process_name TEXT,
            target_cube TEXT,
            write_point_id TEXT,
            operation TEXT,
            dim_index INTEGER,
            dim_expr TEXT,
            dim_value TEXT,
            conditions TEXT
        )""",
    "ti_business_calls": "CREATE TABLE ti_business_calls (caller TEXT, callee TEXT, params TEXT)",
    "ti_framework_calls": "CREATE TABLE ti_framework_calls (process_name TEXT, callee TEXT, purpose TEXT)",
}

# 审计层：前端 Excel 资产 → 后端 Cube 映射（tm1audit 独有）
AUDIT_TABLES: dict[str, str] = {
    "excel_assets": """
        CREATE TABLE excel_assets (
            menu TEXT,
            blob_name TEXT,
            asset_type TEXT,
            risk TEXT,
            link_status TEXT,
            excel_path TEXT,
            has_tm1 BOOLEAN,
            formula_count INTEGER
        )""",
    "front_backend_mapping": """
        CREATE TABLE front_backend_mapping (
            menu TEXT,
            excel_file TEXT,
            backend_cubes TEXT,
            cube_count INTEGER
        )""",
}

ALL_TABLES: dict[str, str] = {
    **OBJECT_TABLES,
    **RELATION_TABLES,
    **LINEAGE_TABLES,
    **AUDIT_TABLES,
}

# 分层元信息（用于 CLI status / 文档）
LAYERS: dict[str, dict[str, str]] = {
    "object": OBJECT_TABLES,
    "relation": RELATION_TABLES,
    "lineage": LINEAGE_TABLES,
    "audit": AUDIT_TABLES,
}

# 增量列迁移：对已存在的旧库补列（CREATE TABLE IF NOT EXISTS 不会改已有表结构）。
# 每项为 (表名, 列名, 列类型)。使用 IF NOT EXISTS 保证幂等，不破坏历史快照。
COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("chores", "start_time", "TEXT"),
    ("chores", "frequency", "TEXT"),
    ("chores", "execution_mode", "TEXT"),
    ("chores", "active", "TEXT"),
]
