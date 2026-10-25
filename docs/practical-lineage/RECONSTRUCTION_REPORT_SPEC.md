# TI 重构研究报告 v1

状态：Phase 2 已实现有限版本；不是运行验证或自动迁移。

页面和导出共用 `workflow_review.build` 的 `ti-reconstruction-review-1` 投影，数据来自既有 Workflow artifact 和只读直接 Chore 索引。

`GET /api/workflow/tasks/{task}/review` 返回 JSON；`?download=true` 设置 JSON 附件响应头；`?format=markdown` 返回 `TI-Reconstruction.md`。

## 阅读层级
1. 一页摘要：当前 TI 名、直接读写对象、直接调用/入口 Caller/独立写入数量和值来源/坐标缺口。无法从源码确认业务用途时仅给静态处理描述。
2. 工程明细：真实调用端点、显式参数绑定、未求值条件、源码位置、入口索引、直接 Chore 定义、四个 Section 字符数、逐写入目标/表达式/坐标/静态读取依赖和重构前检查项。
3. 证据与范围附录：缺失证据、预算、模型指纹；UI 折叠保存原绑定、行变量元数据、循环、解析身份，并可按需读取源码。

原始 TI 全文不会重复嵌入每条关系；原 Workflow 技术工作台、JSON/Markdown 及 Formation 加工证据入口保留。UI 的原始函数名可以在证据层核对，写入操作主表使用覆盖数值/覆盖文本/累加数值。

## 不确定性
共同读写不证明值流。独立写入仅依赖该 write.read_nodes 里的源读取；缺少行值绑定保持未知。Caller 索引不等于源码调用证明；Chore 调度定义不等于执行记录；BFS 发现层数不等于时间顺序；Rule/Feeder、权重、清空、异常、重复执行等仍需验证。

完整迁移规格、汇总权重核验、外部数据源字段补采及真实模型验收不属于该报告版本。
