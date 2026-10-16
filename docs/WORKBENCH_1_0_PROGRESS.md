# Workbench 1.0 进度

> 任务：把 TM1 Insight 已有的模型浏览 / 对象导航 / 代码生成能力，优化为高效、稳定、用户愿意每天使用的专业 Workbench。
> 纪律：保留已有功能/数据/API，禁止引入 AI/LLM/RAG/向量库/云服务，不 Push（除非用户明确授权）。

## 阶段 A：基础体验 ✅ 完成

### A1 跨页面状态记忆
- 新增 `src/tm1_insight/api/static/workbench-context.js`：统一 WorkbenchContext API（版本化 + 按模型指纹隔离 sessionStorage；长期偏好用 localStorage 风格）。
- `app.py` 新增 `_model_fingerprint()` 模板全局；`base.html` 注入 `<body data-model-fingerprint=...>` 并加载 workbench-context.js。
- Cube 列表/详情改用 WorkbenchContext（`rememberList`/`recallList`），Chore 补上 rememberList。
- TI 已有 source 隔离记忆（process-search.js），保持不动。

### A2 Cube 页面重构
- 写入 TI 改为紧凑列表 + 搜索 + 分页（>20 个 TI 时分页，默认每页 20），点击展开写入点详情。
- 固定常量高亮：`const-lit`（固定值，如 Scenario=ACT）/ `param-inline`（参数 pScenario）/ `var-local`（未溯源变量）三种样式区分。
- 数据来源区域中性化：「数据从哪来」→「数据形成」，「谁读它」→「使用与去向」，措辞不再声称确定的数据传输（"不代表值一定由此传输"）。
- 保留 Rule 展示、血缘、对象跳转。

### A3 Dimension 表格体验与性能
- 属性列选择偏好持久化（`dimension-tree.js` 用 WorkbenchContext preference 按维度名隔离）。
- **性能优化**：`dimension_tree.py` 超大维度（>5万元素）降级路径去掉 ORDER BY + 用声明 element_count 替代全量 count，`search_elements` 大维度分支去掉 ORDER BY。
  - 实测（68 万元素合成维度）：tree_summary 2.18s → 0.32s；search 2.05s → 1.28s（剩余为真实匹配数统计，功能必需）。

### A4 测试
- 新增 `tests/test_workbench_context_cube.py`（6 用例）：model_fingerprint 注入、workbench-context 版本化/隔离/无凭据、Cube 紧凑列表/搜索/固定值高亮/中性措辞/Rule 与跳转保留。
- 新增 `tests/test_workbench_dimension_perf.py`（4 用例）：大维度降级正确性、真实匹配数、性能阈值、小维度不受影响。

## 修改文件（阶段 A）
- `src/tm1_insight/api/app.py`
- `src/tm1_insight/api/templates/base.html`
- `src/tm1_insight/api/templates/cubes.html`
- `src/tm1_insight/api/templates/cube_view.html`
- `src/tm1_insight/api/templates/chore_view.html`
- `src/tm1_insight/api/static/workbench.css`
- `src/tm1_insight/api/static/workbench-context.js`（新增）
- `src/tm1_insight/api/static/dimension-tree.js`
- `src/tm1_insight/store/dimension_tree.py`
- `tests/test_workbench_context_cube.py`（新增）
- `tests/test_workbench_dimension_perf.py`（新增）

## 下一阶段
- 阶段 B：TI 计算检查降噪 + Chore 调度信息补采与显示。

## 阶段 B：功能整理 ✅ 完成

### B1 TI 计算检查降噪
- `calculation.html`：把「④ 仍需查证的定义」（UNKNOWN 列表）改为默认折叠的 `<details>`，避免技术噪音干扰阅读。
- 计算检查本就是 TI 页面的独立入口（`计算检查` 按钮 → `/calculation` 独立页），已处于次要位置；`system=false` 默认隐藏 `}` 前缀系统 Cube 写入。
- 未改动 Calculation IR / 语义推断 / 解析引擎（只整理入口与展示）。

### B2 Chore 调度信息补采与显示
- `schema.py`：chores 表增量加列 `start_time/frequency/execution_mode/active`，新增 `COLUMN_MIGRATIONS` 幂等迁移表。
- `db.py`：`init_schema` 建表后执行 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（旧库补列，不破坏历史快照）。
- `client.py` `fetch_chore`：补充采集 `active` 字段（原已采集 start_time/frequency/execution_mode）。
- `loader.py`：chores 入库保存 7 列（调度字段）。
- `queries.py` `get_chore`：返回 `schedule` 字段，旧库无调度列时回退（兼容）。
- `chore_view.html`：详情区顶部显示「启用状态 / 计划执行时间 / 执行频率 / 执行模式」，明确区分「调度定义」与「实际执行」（"不代表实际已执行成功"）。
- `datasource.py`：demo 数据补调度字段（用于演示），demo 库 chores 插入改为 7 列。

## 阶段 C/D：代码生成回归 + 最终回归 ✅ 完成

### C1 代码生成
- 现有模板（data_transfer / data_export / data_export_dim / dimension_maintain / logging_init）已覆盖提示词建议的高频场景，功能完整、测试通过，**不重复开发新模板**（遵循"超出工作量时优先保留现有能力"）。

### D1 最终回归
- 全量测试：**562 passed**（基线 547 → +15 新增用例，无回归）。
- Python `py_compile` + JS `node --check` 全通过。
- 旧库 migration 幂等性 + 旧快照兼容验证通过。

## 修改文件（阶段 B/C/D 追加）
- `src/tm1_insight/store/schema.py`
- `src/tm1_insight/store/db.py`
- `src/tm1_insight/tm1/client.py`
- `src/tm1_insight/ingest/loader.py`
- `src/tm1_insight/store/queries.py`
- `src/tm1_insight/api/templates/chore_view.html`
- `src/tm1_insight/api/templates/calculation.html`
- `src/tm1_insight/api/static/workbench.css`
- `src/tm1_insight/datasource.py`
- `tests/test_workbench_chore_schedule.py`（新增，5 用例）
- `tests/test_chore_workspace.py`（更新 chores 插入为显式列名）
- `tests/test_architecture.py`（更新 chores 插入为显式列名）

## 状态：本轮 Workbench 1.0 全部完成（阶段 A/B/C/D），未 Push（待用户授权）。
