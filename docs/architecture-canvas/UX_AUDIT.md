# Architecture Workbench 交互审计

日期：2026-10-22。分支：`codex/canvas-excellence-04`。开发基线：`0f79bcf`。

本轮只使用源码、隔离测试库和合成样例；未读取现有企业 collections。任务书中的 canvas4 对应实际存在的 canvas-excellence-04 分支，不创建替代分支。

| 观察 / 根因 | 代码证据 | 本轮处理 |
|---|---|---|
| 空搜索直接列出数据库名称前 40 项，缺少任务上下文 | `api/workbench.py:objects` 按名称排序；`architecture-workbench.js:search` 启动时无条件请求 | 空搜索改为引导和按模型隔离的最近访问；不自动选第一项 |
| `}` 是系统命名标记；`Sys Parameter`、`#######` 不能仅凭名字认定系统对象 | `workbench.py:indexed_graph` Cube 名称来自 cubes 表，无完整业务用途分类 | 仅对 `}` 做明确的显示过滤；其他合法名称不删除、不改写。合成样例覆盖这三类名字，未据此声称检查过真实企业记录 |
| 左侧探索范围、分组、设计向导同时存在 | `architecture_workbench.html` 的 `.cx-rail-sec`、`#ew-design` | 左栏默认收起；范围与模块折叠；创建时只打开相关表单 |
| 详情是按钮、全部邻接关系、维度、源码入口和诊断的线性堆叠 | `architecture-workbench.js:panel/showNode/showEdge` | 新增共享 Inspector presenter；概览 / 源码与证据两层；TI 自动显示已有 writes API 的简明摘要 |
| 高度连接节点自动触发环形布局 | `canvas-layout.js:compute` 的 starLike 分支 | 环形仅保留为显式兼容策略，默认分层；循环用 SCC 保留，不推断循环内执行顺序 |
| 点击大圆形反馈仍可能来自 Cytoscape core，单独关闭节点 overlay 不够 | `canvas-graph.js:styleSheet` 原只有 node/edge overlay 设置 | 关闭 core `active-bg-opacity` / `active-bg-size`，保留小幅选中边框 |
| 局部展开无条件清空手工坐标 | `architecture-workbench.js:explore` 原 `positions={}` | 合并展开保留已有坐标；新查询和显式自动布局仍可重新排列 |
| 关闭详情和 Esc 清空选择，破坏连续探索 | `tm1-canvas-escape` | 只关闭详情，保留选择；清空选择保留在更多菜单 |

保留：Cytoscape 离线画布、Cube 图标色板、候选虚线 / Rule / Feeder 类型、关系筛选、拖动与框选、图表联动、原有生成器、工作区 v3、源代码高亮、证据契约和旧路由。没有改 Parser / Dependency / Lineage / Rule IR、正式数据库或模板算法。

本轮基线：1093 passed，0 failed，1 条既有 Starlette 弃用警告。浏览器原有验收脚本依赖旧模式按钮，交接中要求迁移为可见的创建入口；未将这些旧脚本的历史成功记录充作本轮验收。
