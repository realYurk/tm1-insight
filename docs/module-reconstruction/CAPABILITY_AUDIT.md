# 模块重构规格：开发前能力审计

基线：2026-10-25，codex/canvas-excellence-04 / 3604975，工作区干净，本地领先远程 1 个提交。完整阅读产品宪法、AGENTS 与本轮任务书。

| 能力 | 复用位置 | 本轮处理 |
|---|---|---|
| 稳定对象身份与有界关系探索 | workbench.stable_id / GraphQuery / indexed_graph / query_graph；API 的 fingerprint 与 index 缓存 | 范围预览适配，不重新实现图遍历；排除项在遍历前过滤 |
| TI 计算、写入、VIEW、变量链 | workflow.build / artifact；workflow_review.build / source_declaration；store.calculation / data_row | 一个多入口、禁止隐式扩展的 Workflow 结果；小幅适配 review 支持指定成员 |
| Rule、Feeder、Expression IR | store.queries.cube_rule_semantics；learning.rule_semantics / rule_expression | 只解析已选择 Cube，保留 Rule 与 Feeder 独立记录，不从文件级索引确认依赖 |
| Cube 维度顺序、层级与缺失状态 | cube_has_dimension；store.dimensions.metadata、dimension_metadata | 限定已选 Cube，记录已采集摘要，不装载全部成员或推断权重 |
| 行为分类与证据展示 | architecture.OPERATIONS / LABELS；已有写入坐标契约 | 复用操作类别；未纳入的辅助 TI 只保留调用和边界，不能猜测其清空效果 |
| 任务、取消、磁盘缓存 | tasks.TaskManager | 新任务命名空间，逐对象进度与来源检查；不新建任务引擎 |
| 原有导出与报告 | workflow_review、Cube lineage、Functional Flow | 新规格只有一个组装结果，Markdown 与页面从它投影；保留旧接口 |

真正缺失的是用户确认并冻结的模块范围、独立研究定义和人工注释存储、跨对象的统一规格及验证清单。研究定义保存在用户目录，不能写回 Snapshot。预览和生成分开，生成只分析确认的成员，不偷偷继续递归。

不能由当前静态信息确定：动态调用实际目标、参数实际值、MDX 行布局、缺失 Variables、成员全集、跨独立 TI 的运行顺序、累加重复执行结果、清空实际成员范围及迁移等价。报告逐项给出影响、核对方式及证据。

最小修改范围：模块规格组装器、API/任务适配、表格报告与范围表单、既有 Cube/TI/架构入口链接、合成测试及文档。不会开发新画布、Parser、AI、迁移或分摊引擎。兼容风险集中在模型身份、旧快照缺表、范围截断与缓存键；使用可选适配参数和严格版本化定义，保留所有旧路由。
