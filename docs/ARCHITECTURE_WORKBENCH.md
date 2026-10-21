# ARCHITECTURE_WORKBENCH — 连续探索工作台

> 本文只描述**已实现**的行为。所有接口、阈值与语义均可在源码中逐条核对。

## 1. 定位

工作台把「模型浏览 → 血缘 → 架构理解」压缩到同一屏：左侧对象检索与探索范围，中间图 + 关系表，右侧对象详情与源码。
切换对象不换页、不清空画布；所有状态落在**用户工作区**，与采集快照分离。

入口：

- `/architecture?view=workbench`
- `/architecture?view=workbench&kind=cube&name=<cube>`（从 Cube 详情页跳入）
- `/architecture?view=workbench&kind=process&name=<TI>`（从 TI 页跳入）

顶部导航「业务架构」默认指向工作台；原「业务流程与架构分析」保留在同页链接与 `/architecture`（不带 `view` 时）。

## 2. 组件

| 层 | 文件 | 职责 |
|---|---|---|
| 查询内核 | `src/tm1_insight/workbench.py` | 索引投影、有界遍历、预算、工作区 Schema 与原子保存 |
| 关系语义 | `src/tm1_insight/workbench_rules.py` | 把 `cube_rule_semantics` → `unified_relations` 的 Rule/Feeder 事实投影为图边 |
| HTTP | `src/tm1_insight/api/workbench.py` | 7 组端点，全部只读打开 DuckDB |
| 前端 | `static/architecture-workbench.js` | 图、表、详情、多选、编组、草稿、保存恢复 |
| 持久化 | `static/workspace-persistence.js` | `fetch` 封装、导出 |
| 模板桥 | `static/workspace-codegen.js` | 往返现有代码模板 |
| 渲染 | `static/mermaid-viewer.js` | 离线 Mermaid，多实例 + 框选 + 边点击（`v=3`） |
| 源码 | `static/syntax.js` | 行号 + 语法高亮，工作台不另建源码组件 |

## 3. 关系语义（不允许混淆）

| `kind` | 含义 | `status` | 是否值流 |
|---|---|---|---|
| `TI_READ` | TI 读该 Cube | `INDEX_OBSERVATION` | 否 |
| `TI_WRITE` | TI 写该 Cube | `INDEX_OBSERVATION` | 否 |
| `TI_CANDIDATE` | 同一 TI 同时读 A、写 B | `CANDIDATE` | **否**，仅候选加工 |
| `RULE_REFERENCE` | Rule 中 `DB()` 声明的计算依赖（他 Cube → 本 Cube） | `SOURCE_CONFIRMED` | 声明式计算依赖 |
| `FEEDER_REFERENCE` | Feeder 中的 `DB()`（本 Cube → 他 Cube） | `SOURCE_CONFIRMED` | **否**，稀疏性支持 |
| `CALL` | `process_calls_process` | `INDEX_OBSERVATION` | 否，非运行顺序 |
| `SCHEDULE` | `chore_runs_process` | `INDEX_OBSERVATION` | 否 |
| `STRUCTURE` | `cube_has_dimension` | `INDEX_OBSERVATION` | 否，默认隐藏 |
| `RULE_SOURCE_REFERENCE` | 文件级 `rule_references_cube` 索引 | 内部发现用 | **从不返回**给前端 |

要点：

- 文件级索引包含注释与 Feeder 文本，**不能**当计算箭头。它只用于发现「哪些 Cube 有 Rule 值得解析」，解析结果替换后才能出现在图上。
- Rule 与 Feeder 的边方向相反、`line` 不同、`id` 不同，不会被合并。
- 每条边都带 `runtime_verified: false` 与 `unresolved_reasons`。
- 节点带 `provenance`：`MODEL_FACT`（快照内真实存在）/ `STATIC_ANALYSIS`（只是被索引提及）/ `USER_INTERPRETATION`（人工模块）/ `DESIGN_DRAFT`（草稿）。

## 4. 对象身份

```python
stable_id(snapshot, kind, name) = sha256(json([snapshot, kind, name]))[:32]
```

- 身份**含快照**：同名 Cube 在两个快照中 id 不同，不会互相顶替。
- 工作区保存 `snapshot_id`；加载时若当前模型指纹不同 → `409`，提示切回原模型或新建工作区，绝不按名称自动重绑。
- 保存前校验：工作区引用的对象必须仍在当前快照内，否则 `422`，要求保留为设计草稿。

## 5. 查询契约

`GraphQuery`（`extra='forbid'`）：

| 字段 | 约束 |
|---|---|
| `objects` | ≤120 个 `{type,name}` |
| `depth` | 0–6（0 = 只看入口对象自身） |
| `node_budget` | 2–120 |
| `edge_budget` | 1–300 |
| `source_prefix` / `target_prefix` | 前缀选入口，每页 20 个来源，`seed_offset` 翻页 |
| `direction` | upstream / downstream / both |
| `view` | `cubes`（Cube 主干投影） / `objects`（对象与直接读写） |
| `include_technical` | 默认 `false`，过滤名称以 `}` 开头的系统对象 |
| `relation_types` | 显式关系过滤 |

返回 `limits`：

| 字段 | 含义 |
|---|---|
| `truncated` | **因预算**丢弃了结果（节点/边/路径/前缀分页） |
| `boundary` | 局部视图边界外仍有对象（常态，不等于截断） |
| `rule_scope_complete` | Rule 语义分析是否覆盖本次全部所属 Cube |
| `next_seed_offset` | 前缀分页游标 |
| `paths_truncated` | 路径枚举达到 100 条上限 |
| `missing` | 入口对象不在当前快照 |

`rule_scope` 单独给出 `owners_considered / owners_analyzed / owners_skipped / complete`。
单次查询最多解析 **12 个** Cube 的 Rule 文件，单文件上限 **256,000** 字符；超限不解析、也不把未分类引用升级成计算关系。

## 6. 工作区持久化

位置：`<user_data_root>/workspaces/<32位hex>.json`，与 DuckDB、快照目录完全分离。

| 项 | 实现 |
|---|---|
| Schema | `architecture-workspace-1` |
| 体积上限 | 1 MB（读、写双向校验） |
| 并发 | `sha256` 版本号；版本不符 → `409`，不覆盖 |
| 原子性 | `mkstemp` → `write` → `flush` → `fsync` → `os.replace` |
| 回滚点 | 覆盖前保留单份 `<key>.json.bak` |
| 路径安全 | key 必须匹配 `^[a-f0-9]{32}$`，不接受用户传入路径 |
| 损坏文件 | `422` 并保留原文件，列表页显示「不可读取（原文件保留）」 |
| 引用完整性 | 悬挂引用直接拒绝保存 |
| 来源类型 | 模块固定 `USER_INTERPRETATION`，草稿固定 `DESIGN_DRAFT`，不可伪造为 `MODEL_FACT` |

保存内容：名称、快照、查询条件、对象集、选中、可见、关系 id、隐藏、模块（含成员/备注/折叠）、草稿（维度按序）、备注、MDX 文本、视口、模板引用。

MDX 只保存与静态解析，**不执行**；`Scenario=SP75, Version=WIP` 这类切面描述与完整 MDX 语句在 UI 中同一输入框，但不会因未解析而伪造成功。

## 7. 交互

| 交互 | 行为 |
|---|---|
| 单击节点 | 右侧切换详情，画布与选中保持 |
| Ctrl/⌘ 点击 | 多选 |
| Shift 拖动 / 「框选模式」 | 框选节点 |
| 拖动空白 | 平移画布 |
| 点击边 | 右侧显示语义 + 自动定位关系表对应行 |
| 点击关系表行 | 图上高亮对应边与两端节点 |
| 创建模块 | 选中对象 → 填名称 → 生成 `USER_INTERPRETATION` 模块，**同一对象可属多个模块** |
| 折叠模块 | 成员收拢为一个代表节点，只影响展示 |
| 局部隐藏 | 隐藏节点，不删除数据 |
| 保存 / 另存 / 打开 / 导入 / 导出 | 均走工作区文件，不影响快照 |

## 8. 源码与写入切面

- 源码统一使用 `syntax.js`：行号 + 高亮 + 复制，与其它页面一致。
- TI 写入面板默认可见**切面聚合**：
  - 固定目标切面：`维度 = 成员`
  - 运行时 / 动态坐标：`维度 = vXxx（运行时变量）`
  - 待确认坐标单独列出，不猜测
- 逐条写入给出：`section:line`、写入方式（`CellPutN` / `CellIncrementN` / `CellPutS`）、值表达式原文、Data 行绑定状态。
- 值表达式 `vValue` **原样显示**，不推断其来源字段；`MISSING_VARIABLE_METADATA` 时明确提示「旧快照未保存 Process Variables」。
- 维度名来自真实 Cube 维度顺序；无法确认时显示「维度待确认」。

## 9. 代码模板往返

1. 工作台选中恰好 2 个 Cube → 出现「将两个 Cube 带入现有代码模板」。
2. 先保存工作区（确保有 `workspace_id`），再跳 `/codegen?workspace_id=…&source=…&target=…&snapshot_id=…`。
3. 模板页 `workspace-codegen.js` 校验：工作区存在、快照一致、两个对象确实在工作区内 → 填入 `tr-scr` / `tr-tgt` 并切到「数据传输」页签。
4. 页面提供「返回原工作区」链接，回到 `/architecture?view=workbench&workspace_id=…`。
5. 返回后恢复工作区名、选中、图、模块、备注、MDX。

未自动完成的：维度映射、成员映射、方向确认。模板页明示「请核对方向，点击加载维度结构后继续使用原有模板」。

## 10. 当前限制

- 索引在进程内一次性构建（约 0.7s 冷启动），不随查询增长；超大模型下内存与首次延迟需按实际规模复核。
- 单次查询只解析 12 个 Cube 的 Rule，超出时 `rule_scope_complete=false`，UI 明示。
- `TI_CANDIDATE` 永远是候选，不能作为值流结论。
- 调用/调度关系不代表运行顺序。
- 外部数据源只展示类型与已采集声明，不打开文件、不执行 SQL、不含连接信息。
- 草稿 Cube / 草稿关系不会写入 TM1，也不会进入血缘计算。
- 工作区不参与版本控制（`.gitignore`），也不随 Portable 分发包携带。

---

# 第二部分：Visual Development 2.0（设计模式）

> 详见 `DESIGN_MODE.md`、`MAPPING_CONTRACT.md`、`CODEGEN_BRIDGE.md`、`BLUEPRINT_SCHEMA.md`。

## 11. 模式与状态

- 顶栏「探索模式 / 设计模式」切换，共用同一画布与同一工作区（`architecture-workspace-2`）。
- `design.mode` 随工作区保存；切换不清空画布、选中、备注、MDX 与人工模块。
- 设计对象全部带 `DESIGN_DRAFT` / `DESIGN_RELATION` 来源标记，不参与服务端血缘计算。

## 12. 设计对象与渲染

| 对象 | 渲染 |
|---|---|
| Cube 草稿 | 黄色虚线节点，标注「Cube 草稿 · 未部署」 |
| CSV Schema | 紫色虚线节点，标注「CSV Schema · 未接入」 |
| 设计关系 | 虚线边，标注「设计关系 · 未部署」 |

点击草稿节点 → 右侧详情显示维度顺序、每个维度位来源（快照/草稿 id）、创建说明入口。
关系表新增「设计关系」类型过滤项。

## 13. 设计 API

| 端点 | 说明 |
|---|---|
| `GET /api/workbench/design/meta` | 快照维度/ Cube 名（只读）、可用模板；受限说明 |
| `POST /api/workbench/design/validate` | 逐关系返回阻断原因 |
| `POST /api/workbench/design/generate` | 调用既有 `store.codegen` 产出 TI 草案；阻断时不返回代码 |
| `POST /api/workbench/design/cube-spec` | Cube 创建规格与步骤 |

## 14. 生成与部署的边界

- 生成结果为 `DESIGN_DRAFT`，未在 TM1 Server 部署或执行。
- 依据既有 `}APQ` 框架模板输出 prolog / metadata / data / epilog 四段。
- 目标维度顺序来自草稿声明或快照，写入语句参数顺序与之一致。
- 任一映射缺失即 `status=blocked`，不产出空赋值。

## 15. 设计模式限制

- 无自由拖拽建边：关系用「来源/目标」选择建立（准确性优先）。
- 无一对多 / 聚合 / 分配映射；此类需求保持未映射并被阻断。
- `LOOKUP`、`FROM_CONTEXT` 目前保存意图但不生成代码。
- 未做部署、未做运行验证、未做 Cube 实际创建。
- Blueprint 仅支持同 Snapshot 内保存与重开。
