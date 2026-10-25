# Reconstruction Readiness 1.0：代码差距审计

日期：2026-10-25。基线：`codex/canvas-excellence-04` / `7d29e3ef41727cfaceef97bbf413711ffc7b1533`，开始时工作区干净。本轮仅使用合成模型与独立临时目录；没有连接企业服务或分析企业数据。

已完整阅读 PRODUCT_CONSTITUTION.md、AGENTS.md 和本轮任务书。所属产品层：Lineage & Relationships → Architecture Explorer；不增加解释器或业务语义推测。

## 现有能力与实际缺口

| 范围 | 已有实现与证据 | 缺口及本轮处理 |
|---|---|---|
| 架构只读 | `architecture_workbench.html` 的 data-read-only；`architecture-workbench.js` 的 changed/save/remember、beforeunload 与设计入口 gate | 已实现，不重写。实际打开历史资产、点击节点、展开、缩放、临时布局及退出验证；保留草稿和记录 |
| Cube 关系 | `workbench.indexed_graph/query_graph` 的 TI_READ、TI_WRITE、CALL、SCHEDULE、STRUCTURE；Cube 投影的 TI_CANDIDATE；workbench_rules 的 Rule 引用 | 原关系语义可复用；原摘要只呈现最后核对 TI 的首个写入点，缺覆盖度和有限报告。改为独立记录回填、预算队列及范围导出 |
| 写入解释 | `store/calculation.py` 的 inspect、`store/data_row.py` 的 context/attach，已有静态值链和坐标 | 不重做 Parser/DAG。补充 API 中已有 data_row_lineage 字段，投影只消费已确认依赖 |
| TI 报告 | workflow 的有界调用遍历、参数、条件、源码索引；workflow_review 的可读投影 | reads 只有显式 CellGet，VIEW 来源摘要缺失；write_fields 丢掉 Data Row 依赖。分别保留声明、变量、布局和每写入点依赖 |
| 数据源声明 | architecture_extraction.datasource 已有源码声明解析；process_source_metadata 已有带源码哈希的元数据 | 行绑定在 Variables 缺失时提前返回，不能用它替代独立的数据源声明。新增 scoped adapter，复用原解析并校验元数据哈希/动态覆盖，不推断值流 |
| 研究连续性 | Cube/TI/架构已有路由、对象名链接 | 链接未固定模型身份。新增可选 model 参数并校验，旧链接继续可用 |
| Mermaid | mermaid-viewer.js 已有适应、缩放、方向、下载、dispose；表格为主 | 复用，无新图引擎；本轮验证自环、方向、适应和退出，既有自动化覆盖滚轮、resize、dispose |

## 范围、风险和验收

最小闭环为 Cube 关系查询 → 有限核对 → 独立切面回填 → TI 调用/数据源研究 → 两类报告。没有扩展分摊、代码生成、设计画布或导航体系。

风险主要是共同读写被错误提升、元数据过期、取消后迟到结果污染、报告范围混淆、模型切换。正反例分别检查独立常量、动态 VIEW、哈希不匹配、Abort 迟到响应、409 和覆盖度。详见 ACCEPTANCE_REPORT.md。

仍需要补采才能解决的部分：Variables、NativeView 布局/值列关系、动态 MDX、成员筛选、运行时参数。这里只如实报告，不访问服务器，不放宽核心语义。
