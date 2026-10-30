# 01 代码审计

基线：本地和远端 master 为 bb92196；工作区原本干净。审计范围为本轮入口、关系、计算、规格及发布路径，不能理解为所有代码已逐行审完。

## 已复现
- `workbench.py:query_graph` 原先先全局组合 TI_READ × TI_WRITE，再以 50000 条唯一候选为限：合成 3000 Cube / 3000 TI、无关 230×230 组合时，后部目标返回 0 条候选且标记截断。见 `tests/test_hardening_scoped_candidates.py`。
- `cube-lineage.js` 原先 `selected.slice(0,24)` 向模块规格静默传递前 24 项；`module-spec.js` 原节点预算 24，存在二次范围损失。
- `scripts/browser_acceptance.py:47` 的 `page.title() or True` 永真；已改为检查实际标题，但脚本其余流程未完成本轮重验。

## 已有能力及边界
- `workbench.py:indexed_graph` 复用只读索引；`api/workbench.py:graph` 局部复核 Rule 所属 Cube，Rule 范围有独立预算。
- `store/calculation.py` 提供写入、坐标、读取节点与证据；`store/data_row.py` 保留变量、View 布局与缺失状态；静态值依赖不代表运行验证。
- `workflow.py`、`workflow_review.py` 提供调用、参数、条件与缓存；调用和 Chore 定义不代表实际执行。
- `module_spec.py` 固定 members、排除和预算，`functional_flow.py` 投影统一关系并标明截断；多份展示投影仍需一致性核验。
- `lineage-view.js` 为显示设节点预算；`cube-lineage.js`、`ti-lineage.js` 有中止、模型身份与失败处理。`canvas-graph.js` / `canvas-layout.js` 与 `mermaid-viewer.js` 负责显示而非值流推断。

## 高风险、未复现
- 高扇入下明细请求和缓存重开、模型切换时迟到请求，仍需浏览器并发测试。
- 候选预算为 50000；局部范围本身仍可能超过预算，未精确计数被遗漏候选；Rule 复核和后台取消延迟未测。
- 公开仓库历史中对象名称和本机路径存在授权风险；历史报告不等于本轮全面历史审计。

## 体验问题
多页面重复组织证据，原始枚举与缺失状态仍可造成负担；导出与页面一致性未做全链验证。

## 发布检查范围

本轮 `git ls-files` 检查 `.env`、DuckDB、WAL、Parquet，未发现被跟踪文件；`git log --all` 对这些扩展及 `.env` 的路径历史查询结果为空。这不是对所有历史对象、凭据或授权的全面证明。原公开仓库审计已列出对象名及路径风险，本轮未改写历史。
