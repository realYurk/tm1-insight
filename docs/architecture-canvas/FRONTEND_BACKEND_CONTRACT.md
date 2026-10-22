# 前后端契约：复用现状

契约依据：`workbench.py`、`api/workbench.py`、`architecture-workbench.js`。本轮没有变更后端响应或 Workspace Schema。

## 对象与关系

`POST /api/workbench/graph` 使用现有 GraphQuery：snapshot_id、objects[{type,name}]、方向、depth、node_budget、edge_budget、view、relation_types、source_prefix、target_prefix、seed_offset、include_technical。

响应保留 nodes、edges、query、limits、limitations、rule_scope。对象 id 由现有 `stable_id(snapshot,type,name)` 生成，不用画布坐标或显示名称作身份。`in_snapshot=false` 的提及不能冒充已采集定义。

边沿用 `id/source/target/kind/label/provenance/status/runtime_verified/evidence/unresolved_reasons`；TI 聚合还含 process_ids/process_names。Rule 边可能带 semantic_status。不同 kind、证据和语义状态不能只按端点合并。没有 writes 数量字段时，不显示虚构的“5 Writes”。

| kind | 表达边界 |
|---|---|
| TI_CANDIDATE | 同一 TI 共同读写，未证明值映射 |
| TI_READ / TI_WRITE | 对象访问事实，精确切面按 writes API 核对 |
| RULE_REFERENCE | 声明式 DB 引用，不是 TI 写入 |
| FEEDER_REFERENCE | 稀疏支持，非数值贡献 |
| CALL / SCHEDULE | 调用 / 调度定义，不是运行次数及顺序证明 |
| STRUCTURE | 结构，不是计算 |
| DESIGN_RELATION | 用户设计，未部署 |

`GET /api/workbench/objects?q=&type=&include_technical=&limit=&offset=` 返回 snapshot_id、objects、total、filtered_technical、offset、limit。Rule 搜索当前按所属 Cube 定位，不创建新的后端对象类型。空搜索默认不调用目录接口。系统对象（`}` 前缀）默认在服务端过滤后再分页，`include_technical=true` 保留全部对象；过滤只针对 `}` 前缀这一采集层系统命名标记，`Sys Parameter`、`#######` 等名称不参与任何「系统 / 业务」判定，不被硬编码排除或改写。

## 详情与切面

`GET /api/workbench/detail?snapshot_id=&type=&name=`：单对象定义、TI 四段源码、reads_cubes/writes_cubes 或 Cube dimensions/rules。

`GET /api/workbench/writes?snapshot_id=&process=`：writes、total。沿用 operation/cube/coordinate_mapping/items/binding、value_expression、evidence、trace_status、data_row_binding_status、data_row_value_dependencies、unresolved_binding_reasons、value_definition_chain。

Presenter 只对 FIXED_MEMBER 显示固定值；PARAMETER / DATA_ROW_VARIABLE / LOOKUP_COORDINATE 保留变量或表达式；其他状态为待确认。不从变量名猜来源。汇总取各写入点观察集合，明确不代表共同切面。当前接口没有完整源切面摘要，不将其伪装成已解析。

`GET /api/workbench/rules?snapshot_id=&cube=`：rules/feeders/unknowns。概览读取规则 lhs.raw、db_references[].cube_resolved、conditions；完整 expression_ir、源码、状态和未确认原因留在证据层。点击 Rule 边只选取引用对应来源 Cube 的规则；不声称匹配到了运行时单元格贡献。

### 概览 ViewModel 的事实 → evidence 映射（v1）

概览（`TM1Inspector.writes/rules`）只做展示，不计算、不改变后端语义。每一项都对应后端返回的原始字段，不做前端推断。此映射随接口版本演进，当前为 v1。

**TI 写入概览（来自 `GET /api/workbench/writes`）**

| 概览呈现 | 后端事实字段 | 边界 |
|---|---|---|
| 写入方式（累加/覆盖数值/覆盖文本） | `writes[].operation`（CellIncrementN / CellPutN / CellPutS） | 操作类别，非业务含义 |
| 目标 Cube | `writes[].cube` | 过滤 `}` 前缀系统对象单独说明 |
| 观察到的固定切面 | `writes[].coordinate_mapping.items[].binding.kind=='FIXED_MEMBER'` 的 `binding.value` | 仅显示 FIXED_MEMBER |
| 运行时坐标 | `binding.kind in {PARAMETER, DATA_ROW_VARIABLE, LOOKUP_COORDINATE}` 的 `binding.expression` | 保留变量/表达式，不从变量名猜来源 |
| 待确认 | `binding.kind` 其余（UNRESOLVED 等） | 不伪装成已解析 |
| 已解析目标写入计数 | `writes.length / total` | 空结果 ≠ 无写入；接口失败/404 显式提示 |
| 限制 | `limitations[]` | 截断/范围限制 |

**Rule 概览（来自 `GET /api/workbench/rules`）**

| 概览呈现 | 后端事实字段 | 边界 |
|---|---|---|
| 相关 Rule 数量 | `rules.length` | `available=false` 或 `error` 时提示「未取得」，不显示为 0 条 |
| 计算目标区域 | `rules[].lhs.raw` | 区域原始表达式，成员归属未运行验证 |
| 已确认引用 Cube | `rules[].db_references[].cube_resolved` 且 `cube` | 仅已解析的声明式引用 |
| 条件分支 | `rules[].conditions` 是否非空 | 实际分支未运行验证 |
| Feeder 条数 | `feeders.length` | 稀疏支持，非数值贡献 |

## 工作区与设计

沿用 `architecture-workspace-3`，保留旧版兼容验证。字段包括 snapshot_id、objects、selected、visible、edge_ids、positions、layout、groups、notes、mdx、design、template_ref。

- 事实对象保留现有身份和 snapshot_id；人工模块 USER_INTERPRETATION；草稿 DESIGN_DRAFT；设计关系 DESIGN_RELATION。
- design 的 cubes/dimensions/schemas/relations/blueprints 沿用既有模型，不另建 UI 专用持久化结构。
- positions 保存模型坐标；layout 保存 zoom/x/y，现有 vertical 键表示 LR(0)/TB(1)。外壳收起偏好为 UI 偏好，不写模型。
- 现有 workspaces GET/POST/PUT、revision 冲突、原子保存及导入导出继续有效。409 不自动改绑同名对象；损坏文件不覆盖。
- 现有 `/api/workbench/design/meta|validate|generate|stale|cube-spec` 是本地草稿能力，不是服务器创建接口。

## 组件接口

新增 `TM1Inspector.mount(host,title,onClose)` 返回概览容器；`technical(parent)` 取得相应技术容器；`stat/list/writes/rules` 只做展示。模块不执行计算、不改变原分析结果。

`TM1CanvasLayout.compute(nodes,edges,{strategy:'layered',direction:'LR'|'TB'})` 沿用原返回 positions/strategy/sccCount。显式 radial 仅为兼容分支，产品默认不用。

## 错误与未接入项

404 显示缺失对象；409 保留当前上下文并要求原模型；查询预算不足显示局部范围；网络取消不发布旧结果。缺少源坐标、业务作用、字段 Schema、变量绑定和运行证据时保留缺失，不由 UI 文案补齐。自动写入切面摘要使用现有接口，不能把接口失败解释为空数据或完整证据。
