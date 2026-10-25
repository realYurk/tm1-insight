# 实施报告

## 产品结果

Cube 关系表现在可以在有限预算内核对、回填独立切面、标注报告覆盖度；TI 报告补回 VIEW 来源与已有行变量值链；跨页面研究固定模型身份。架构保持只读，Mermaid 保持辅助定位。

## 修改文件

| 文件 | 目的 |
|---|---|
| src/tm1_insight/workflow_review.py | 数据源声明适配、分层来源、行为摘要、保留逐写入 Data Row 依赖、三层 Markdown |
| src/tm1_insight/api/workflow.py | 在既有只读连接中提供声明给 review |
| src/tm1_insight/api/workbench.py | writes 增加已有 Data Row 元数据、先检查单 Process 正文预算 |
| src/tm1_insight/api/app.py | 可选 model 参数、源码入口身份校验、research_model 模板 helper |
| src/tm1_insight/api/static/cube-lineage.js | 有限队列、取消/失败/409、缓存复用、覆盖度、独立摘要、双范围导出、模型链接 |
| src/tm1_insight/api/static/ti-lineage.js | 分层来源/字段/值依赖呈现、行为摘要与模型导航校验 |
| src/tm1_insight/api/static/architecture-workbench.js | 只读详情中的 Cube 研究链接保持模型 |
| src/tm1_insight/api/static/functional-flow.js | 对象详情增加当前模型 Cube/TI 研究入口 |
| src/tm1_insight/api/templates/cube_lineage.html | 预算、进度、覆盖、取消与两类导出操作 |
| src/tm1_insight/api/templates/ti_lineage.html | 模型标识与资源版本 |
| src/tm1_insight/api/templates/process_view.html | TI 调用研究入口 |
| src/tm1_insight/api/templates/_cube_detail.html | Cube 血缘入口模型连续性 |
| src/tm1_insight/api/templates/architecture.html | 更新本地 JS 资源版本 |
| tests/test_reconstruction_readiness.py | VIEW 正反例、兼容、预算、身份及控制器测试 |
| tests/ui/cube_review_controller.js | 实际 JS 的有限队列、复用、失败、取消迟到响应和模型变化测试；提交前统一为发布检查允许的 .js 扩展名 |
| tests/test_cube_lineage_ui.py | 保留既有断言，补模型 URL；Node 大脚本改 stdin 避免 Windows WinError206 |
| docs/reconstruction-readiness/*.md | 审计、契约、验收与限制 |

## 安全与实现边界

未修改 Parser、Rule IR、Calculation DAG、DuckDB schema 或采集元数据。不修改正式库，不联网采集。测试服务仅监听 127.0.0.1:8809，独立合成库只读连接，并拒绝非本地网络连接。所有核对 POST 是现有查询/本地分析任务，不是服务器写操作。

没有恢复设计模式、保存草稿、Blueprint 或 AI 功能。保留既有设计代码与用户数据。开发验收完成后，用户授权将本轮代码提交到当前分支；未授权本轮远程推送或合并。

## 后续建议

可以开始有限范围、证据引用明确的模块级重构规格：对象边界、调用入口、参数、写入模式、已确认切面和验收用例。不能直接声称具备自动 Java 迁移或运行等价证明。动态 MDX、实际参数、条件可达性、聚合权重及缺失 Variables 仍需独立证据。
