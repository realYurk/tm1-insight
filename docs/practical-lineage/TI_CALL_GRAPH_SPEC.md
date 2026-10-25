# TI 调用视角 v1（Phase 2）

状态：本轮用户“继续”后增量实施，2026-10-24。Phase 0/1 的只读边界继续生效。

## 已实现
`/graph?ti=名称` 和 `/graph?ti=` 进入 TI 调用与重构视角；Cube 路径不变。复用 `/api/workflow/tasks` 的可取消任务、进度、范围预算、缓存和源码证据，不重写 Parser 或遍历器。

默认三类内容：本 TI 直接读写摘要；调用方/被调用方/参数/条件/源码表；逐写入点与固定/动态坐标。下游其他 TI 的调用单独折叠，保留其真实 process→target。入口 Caller 只有索引时标为未核对源码，不能假称直接执行或补猜参数。Chore 仅列采集的直接调度定义，不补推经 Caller 的最初调度入口。

简图为辅助，使用调用表同一组源码观察；不再把递归 Caller/Callee 列表一律画成中心 TI 的直接边。循环保留；动态目标不补造命名节点；最多 24 TI / 30 调用，超预算表格仍可用。框架调用保留原事实，不按名称猜测副作用。

## 数据与证据
新增 `GET /api/workflow/tasks/{task}/review`，返回 `ti-reconstruction-review-1`。由已有 Workflow artifact 的分页索引、root detail 和只读 Chore 索引投影：
- summary：当前 TI 的直接读写、直接调用观察数、独立写入数和值/坐标缺口数；子 TI 的副作用不混入。
- calls / downstream_calls：现有 source_invocation、bindings、control_context、源码位置；重复调用位置保留。
- callers：原 STRUCTURAL_UNVERIFIED 索引记录。
- schedules：Chore、step_order、可用启用/时间/周期元数据、chore_runs_process 证据。
- writes：兼容 Phase 1 的独立写入、read_nodes、坐标、定义链，未升级静态推断状态。
- sections、parameters、data_row_lineage、critical_unknowns、cycles、budgets、limitations、evidence_context。

每类表格最多 200 条，写入 80 个、保留值依赖读取 160 个；上限显式说明。全量技术记录仍用原 Workflow JSON 导出。旧快照缺少 Chore 表/索引时给出缺失状态，不迁移数据库、不创建表。

源码通过原 evidence API 按需读取 20 行，核对源码哈希；复用共享 syntax.js 高亮/行号/复制。源码在整行中展开，避免窄单元格挤压。

## 边界
没有求值条件/参数、替换跨 TI 公式或验证运行顺序。仅入口 Caller 索引不能确认其源码调用条件。Source Data Variables / View 不足时仍未知。取消按钮取消显示并请求现有任务取消；任务已完成时不能宣称实际中断了运行。
