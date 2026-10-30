# 写入值来源展示契约 v1

范围：复用 Calculation 的逐写入 `read_nodes`、逐读取 `resolution`、Data Row 绑定与源码证据；不重新解析代码。适用于 Workflow、模块规格以及 Cube/TI 逐写入展示。

- `confirmed_source_read_ids`：写入跟踪状态为 STATIC 或 PARTIAL，且写入值链包含该读取、Cube 名存在且 resolution 为 resolved。此状态不证明完整公式或运行结果。
- `confirmed_data_row_dependencies`：以上跟踪状态成立，且数据行绑定状态为 STATIC_CELL_VALUE_DEPENDENCY，来源 Cube 明确、字段为 CELL_VALUE。声明 View、变量名或位置本身不证明值列。
- 动态 Cube、未知跟踪状态、未经确认的 View 字段、无关读取不得计入已确认源值。常量写入没有来源 Cube 不表示解析失败。
- 保留旧 `read_nodes`、`source_reads`、`data_row_value_dependencies`，供技术详情和旧消费者读取；新增字段是严格子集。模块 Markdown 只展示严格子集。老报告缺少新字段时保守显示来源未确认。
- `runtime_verified=false`；条件、成员坐标及不支持的函数可仍为 PARTIAL。

工作流缓存 revision 从 3 升为 4，模块任务 revision 从 1 升为 2；本地已有报告、快照和逐 TI 原始解析缓存保留，不被删除。

取消重开：未完成 Promise 的 AbortSignal 触发后同步从缓存移除；旧请求迟到时不能删除替代请求，已经成功的缓存仍可复用。

验证：合成动态 Cube 的 CellGet 先复现模块规格误标，修复后 Workflow、模块规格和 Markdown 均不再宣称已确认；原有 NativeView 值列及无关读取反例保留。隔离 Demo 浏览器验证关系详情打开、关闭和重开。独立用户验收另见 09。
