# Data Lineage 2.0：实现前审计

日期：2026-10-26。分支 `codex/canvas-excellence-04`，基线 `3adcfc2`；`git status` 干净，已检查本地/远端分支及最近5次提交。不reset、不rebase、不合并主分支。

用户问题是看不清关系和切面，属于产品第二层“关系与血缘”。本轮仅数据血缘，以及业务架构只读边界验证。非目标：新解析器、设计画布、模块规格、Java、AI、业务架构全面改造。

| 检查项 | 真实实现 | 复用/差距 |
|---|---|---|
| 血缘入口与Cube页面 | `cube_lineage.html`、`cube-lineage.js` | 已有Cube投影和右侧；参数/导出过多，关系表默认重复图，选边会丢掉上下文 |
| TI页面 | `ti_lineage.html`、`ti-lineage.js` | 已有真实Workflow后台任务与报告；节点点击重新建任务，不能就地看同范围TI |
| 交互画布 | `canvas-graph.js`、`architecture-workbench.js` | 既有Cytoscape能力大、含历史设计接口；不把设计状态引入血缘 |
| Mermaid | `mermaid-viewer.js` | 已有离线strict渲染、Fit、缩放平移、节点/边点击、导出，选为本轮交互画布；不并排显示第二张等价图 |
| 业务架构 | `architecture.html`、`architecture-workbench.js` | 默认Functional Flow，旧workbench已有只读标记；仅验边界，不扩展 |
| Architecture.md | `architecture.py`、`functional_flow.py`及架构导出路由 | 保留全部，不复制其生成器 |
| Cube读写 | `workbench.indexed_graph/query_graph`、`api/workbench.py` | 共同读写只是候选；`writes`已有逐值read_nodes与来源View，可局部投影状态，不能升级整条候选的所有写入 |
| TI调用 | `workflow.py`、`workflow_review.py` | 有直接/下级调用、Caller索引、条件、参数、循环、动态目标；复用已分析SQLite，增加选中process的报告投影 |
| Rule/Feeder | `workbench_rules.py`、`store.queries.cube_rule_semantics` | Rule DB引用可证实；Feeder独立，不当数值来源 |
| 参数/坐标 | `store.calculation`、`store.data_row` | 固定、参数、View值列、缺失元数据各自保留；不改解析规则 |
| 搜索 | Cube浏览`chore-search/input`、TI搜索、首页`sr-item`视觉与现有对象查询 | 复用样式和API；目前没有可直接挂载的通用键盘combobox，首页Enter还会默认跳首项，因此只补轻量共享交互，不复制错误行为 |
| MD/JSON | `cube-lineage.markdownReport`、`workflow_review.markdown`及原导出 | 已有三层内容基础；优化标题/范围，保持旧字段与路径 |

UI重复主要是：图与关系表同时抢主位、多份完整表格默认展开、图工具栏导出按钮堆叠、深度/方向占据首屏、调查型状态替代结论。已有证据不删，只调整入口和局部投影。

验收：合成General Ledger直接/间接上下游；明确读取值、无关读取/常量反例；多TI与独立写入；Rule非物理写入；多层/条件/循环/动态调用；长名称；100%→150%→60%→100%等比往返；搜索键盘/清空/模型隔离；离开无保存；三层报告及原浏览/代码能力回归。基线专项：25 passed、1 warning、5.31秒；非本轮最终结果。

风险：候选不等于值流；部分写入确认不代表整条关系确认；Caller索引不能当源码证据；有界范围不等于完整图；切面不能跨写入混用。测试和报告需分别明确这些边界。
