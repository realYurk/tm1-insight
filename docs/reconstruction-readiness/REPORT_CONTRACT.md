# 报告契约与范围

## Cube

沿用 `cube-lineage-review-1`，新增可选字段，旧字段保留：

| 字段 | 含义 |
|---|---|
| export_mode | INDEX_SUMMARY 或 SCOPED_RESEARCH |
| review_coverage | relations_total、reviewed、partial、unreviewed、checks_completed、checks_total |
| report_run | budget、planned、attempted、status、cancelled、budget_truncated、failures，可选 model_changed |
| inspected | 独立关系核对记录；索引摘要为 [] |
| writes[].source_data_rows | 已有引擎确认且源 Cube 匹配的值列依赖 |
| writes[].source_row_slices | 同一来源已有坐标映射；动态变量不转固定成员 |

reviewed/partial/unreviewed 互斥，和等于 relations_total。完成数是“关系内机制”计数，同一个 TI 在两条关系中计两项；请求预算按唯一 TI 或 Rule 所属 Cube 计数，因此二者不一定相等。完成不代表 PARSED、运行证明或全模型覆盖。

队列逐个请求既有只读 API，不创建第二分析器。最大 20 项，失败继续；409 模型变化立即停止；取消停止后续请求，忽略迟到结果，保留已完成记录。单个 Python 解析的 CPU 工作不能由客户端 Abort 强制抢占，其正文大小受限。页面关闭/切换查询清理队列与当前缓存。运行中/取消后也能下载，范围状态保留。

摘要与研究报告都输出 Markdown 并附机器可读 JSON。摘要不偷带逐写入明细；研究报告只包含实际完成范围。排序确定，证据不通过 UUID 或时间制造关系身份。

## TI

沿用 `ti-reconstruction-review-1`，保留 reads/writes/calls/conditions 等旧字段。新增：

- summary.view_sources：已确认绑定 Cube 的独立来源描述，不能替代显式 CellGet reads。
- summary.behaviors：基于已观察操作的文字说明。
- sources.declaration/view_binding/variables/coordinates/reasons：分层确认，不折叠成单一值流结论。
- writes.writes[].data_row_value_dependencies：现有值链的投影，保留来源字段、变量、源码与状态。

Markdown 与 JSON 使用相同 review 投影；报告不执行 TI，也不宣称迁移等价。

## 模型与兼容

研究链接的可选 model 使用现有 knowledge_tasks fingerprint，与旧 body/workbench context 的内部标识用途不同。Graph、Workflow 与源码入口校验当前模型；409 不自动切换到新模型。旧 URL 不带 model 继续可访问并绑定当前模型。没有 DB schema、采集库或引擎缓存版本变更。
