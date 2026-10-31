# Module Dossier P0 — 开发前能力审计

基线：2026-10-31，工作区 `tm1-insight`，未提交改动为 `api/app.py`、`templates/cubes.html`、`store/queries.py`、`tests/audit_scope_e2e.py`、`tests/test_cube_scope.py`（本轮不触碰）。

完整阅读：`PRODUCT_CONSTITUTION.md`、`AGENTS.md`、`docs/EXAMPLE_ARCHITECTURE_V2.md`、`docs/EXAMPLE_CUBE_FORMATION_1_0.md`、`docs/DATA_ROW_LINEAGE_1_0.md`、`docs/RULE_SEMANTICS_1_0.md`、`docs/FUNCTIONAL_FLOW_1_0.md`、`docs/module-reconstruction/CAPABILITY_AUDIT.md`、`module_spec.py`、`store/calculation.py`、`store/data_row.py`、`store/dimensions.py`、`store/queries.py::cube_rule_semantics`、`workflow_review.py`、`architecture_extraction.py::package`。

结论先说：**本仓库已有完整的解析与证据引擎，缺的是一个把既有事实按「模块档案」阅读顺序重新组织、并补齐逐字段定位的投影层。** 因此本轮不新增 Parser、图引擎、计算引擎或 Rule 解析器。

---

## 1. 已有且可直接复用的事实

| 档案需求 | 现有来源 | 证据强度 |
| --- | --- | --- |
| Cube 维度顺序 | `cube_has_dimension.dim_order`；`store/calculation.py::coordinates` 已做完整性校验 | 模型事实 |
| Cube 维度数量与一致性 | `cubes.dimension_count`；`complete_order` 判定 | 模型事实 |
| 维度元素/属性/汇总边/子集 | `dimensions.elements/attributes/edges/subsets`；`store.dimensions.metadata()` 返回 recorded/UNKNOWN 与计数 | 模型事实，未求值 |
| 层级名称 | `dimension_metadata.hierarchy_names`（旧快照可能整表缺失） | 采集事实，非层级结构 |
| TI DataSource 声明 | `architecture_extraction.datasource()`：静态顶层赋值、别名、`DataSourceType` 最终覆盖 | 源码事实（仅声明） |
| TI 记录型 DataSource | `process_source_metadata.payload.datasource`（需源码哈希匹配） | 采集事实 |
| Native View 身份与维度顺序 | `process_source_metadata.payload.source_view`（`type=NativeView` + `dimension_order`） | 采集事实 |
| DataSource Variables 名称/类型/位置/字节 | `data_row.context()` → `data_source_variable_bindings` | 采集事实 + 契约校验 |
| 源列 ↔ Cube 维度的静态对应 | `data_row.context()` → `source_coordinate_mapping`（NativeView + 完整维度顺序 + 末列值） | 静态推断（有 IBM 规则依据） |
| 写入点操作与源码位置 | `learning.calculation.worksheet()` → `writes[].operation/evidence` | 源码事实 |
| 写入目标坐标与绑定类型 | `store/calculation.py::_coordinate_bindings` → `FIXED_MEMBER/PARAMETER/DATA_ROW_VARIABLE/LOOKUP_COORDINATE/NUMBER/UNRESOLVED` | 源码事实 + 目录校验 |
| 写入值表达式与定义链 | `writes[].value_expression/formula_expression/definition_nodes` | 源码事实（表达式文本，无 AST 求值） |
| 写入条件与循环 | `writes[].control_context`（kind/section/line/condition，未求值） | 源码事实 |
| 值依赖 vs 共同读写 | `workflow.confirmed_write_sources()`；`data_row.attach()` | 静态推断，明确区分 |
| 数据行变量 → 写入值依赖 | `writes[].data_row_value_dependencies` | 静态推断 |
| Process 参数名 | `workflow.detail()['parameter_names']` | 源码事实 |
| Process 参数类型/默认值 | `process_source_metadata.payload.parameters`（= `parameter_definitions`） | 采集事实 |
| TI 调用与参数绑定 | `worksheet.calls[]`（target/arguments/control_context/status） | 源码事实 |
| Chore 调度 | `chore_runs_process` | 采集事实 |
| Rule 目标区域/表达式/DB 引用/条件/行号 | `store.queries.cube_rule_semantics()` → `rule-semantics-1` | 源码解析 |
| Feeder 独立语义 | 同上 `feeders[]`，与 Rule 分离 | 源码解析 |
| Rule 指令与未知项 | `directives[]`、`unknowns[]` | 源码解析 |
| 稳定证据 ID 与哈希 | `module_spec.py::proof`（`e`+sha256）、`workbench.stable_id` | 可复用模式 |
| ZIP 导出（磁盘 spool、固定时间戳） | `architecture_extraction.package()` | 可复用模式 |
| 任务/进度/取消/缓存 | `tasks.TaskManager` | 可复用 |

## 2. 只是展示层缺失（数据已在库，缺档案化组织）

1. **逐写入点的「数据字段 → 目标坐标」对照表**。`source_coordinate_mapping` 与 `coordinate_mapping` 分别存在，但从未在同一条写入上并置成「源维度/源列 → 目标维度/目标坐标」。本轮新增该投影（纯 join，不推断）。
2. **写入模式的中文契约**。`CellPutN/CellPutS/CellIncrementN` 已在 `OPERATIONS` 中分类，但没有「覆盖/覆盖文本/累加」这一迁移敏感字段。
3. **Rule 作用区域的表格化**。`lhs.raw` 与 `coordinates` 已存在；`module_spec.py` 只输出 `raw` 字符串，未拆分坐标与维度确认状态。
4. **维度属性/层级摘要**。`dimensions.attributes` 与 `dimension_metadata.hierarchy_names` 已在库，但只有维度工作台使用，档案从未引用。
5. **参数类型/默认值**。存在 `process_source_metadata.parameters`，但 `module_spec` 只输出参数名。
6. **Questions.md**。验证缺口已以 `unknowns` 形式存在，但没有面向人工确认的问题清单。
7. **排除项残留告警**。现有排除只影响遍历集合；被排除对象上的依赖没有形成「已知但未分析」的记录。

## 3. 因采集缺失仍无法得到（必须保留 UNKNOWN）

| 缺失项 | 触发条件 | 档案中的处理 |
| --- | --- | --- |
| Variables/DataSource 元数据 | 旧快照无 `process_source_metadata` 表，或四段源码哈希不匹配 | `MISSING_VARIABLE_METADATA` / `METADATA_SOURCE_MISMATCH`，不生成行变量表 |
| 行变量 → 源字段 | 非 NativeView、MDX 视图、视图被本 TI 重建、维度顺序不匹配、多值列 | `ROW_LAYOUT_UNKNOWN`，变量保留名称/位置，`source_field=null` |
| 实际行集合 | Subset 成员、MDX、隐式切片器 | `membership_status=UNKNOWN`，只记录筛选的静态观察 |
| 参数实际值 | 运行时调用参数 | `DECLARED_NOT_EVALUATED` |
| 动态调用目标 | `ExecuteProcess(pTarget)` | `callee=null` + 缺口项 |
| Rule 裸成员归属 | 无成员索引时的 `['AMT']` | `dimension:null`，保留原文 |
| Rule 动态 Cube | `DB(pCube,…)` | `cube_resolved=false` |
| 层级权重/汇总结果 | 未采集 `edges` 或权重超长 | 只报 recorded/UNKNOWN，不求值 |
| 执行顺序 | 静态源码 | 全篇标注「不是执行顺序」 |
| 运行贡献与等价性 | 未执行 TM1 | `runtime_verified=false`，0 项运行验证 |

## 4. 本轮复用边界（明确不做什么）

- 不新增 TI Parser：一律调用 `store.calculation.inspect`。
- 不新增 Rule Parser：一律调用 `cube_rule_semantics`。
- 不新增图遍历引擎：候选发现只读 `process_calls_process` / `process_reads_cube` / `process_writes_cube` / `chore_runs_process` 与 worksheet 的直接调用观察。
- 不新建前端体系：只提供 API 下载与 CLI 生成。
- 不写入 TM1、不修改快照、不迁移旧库；所有连接 `read_only=True`。

## 5. 验收面

1. 只读 `Module.md` 的陌生读者能回答：数据从哪来、经过哪些步骤、写到哪个 Cube 的哪些坐标、结果如何被 Rule 补全、还有哪些没确认。
2. 每个断言都有 `EV-xxxxx` 且能在 `Evidence.json` 定位到对象 + Section/行号。
3. 排除对象仍产生「依赖存在但未分析」的缺口。
4. ZIP 五件套齐全。
