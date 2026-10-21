# DEEPSEEK_HANDOFF — Architecture Workbench 1.0 接力记录

> 本轮：接手 GPT-6 现场 → 审计 → 修复 → 验收 → 提交。
> 原则：不重写、不新建第二套引擎、不伪造证据、不连接企业 TM1。

## 1. 接手时状态

- 分支 `codex/product-evolution-01`，HEAD `8ef6d67`（= master）。
- 9 个已修改文件 + 10 个未跟踪文件，全部为 GPT-6 未提交现场。
- 已备份至 `_handoff_backup_20261021-192717/`（补丁 + 原始文件副本 + HEAD 记录）。

## 2. 本轮完成

### 2.1 审计结论

- GPT 报告的功能**真实存在**，不是 Mock：图查询、关系表、详情、编组、保存恢复、快照隔离、Rule/Feeder 分类、ACT 切面、模板往返。
- 报告中的数字与文档**不准确**：专项测试实为 26 项（非 22）；5 份交接文档**未落地**。
- 发现 8 处真实缺陷，全部修复（清单见 `CURRENT_STATE_AUDIT.md` 第 3 节）。

### 2.2 代码改动（14 个已跟踪文件 + 6 个新文件）

数据安全：

- `.gitignore`：新增 `workspaces/`。工作区含企业对象名/备注/MDX，此前位于仓库根目录且未被忽略。

语义修正：

- `src/tm1_insight/workbench.py`：`truncated` 只表示「因预算丢弃结果」；视图边界由 `boundary` 单独表达。
- `src/tm1_insight/api/workbench.py`：Rule 分析预算不足改记 `limits.rule_scope_complete`，不再污染 `truncated`。

可读性 / 性能：

- `static/architecture-workbench.js`
  - 写入面板新增默认可见的「固定目标切面 / 运行时坐标 / 待确认坐标」聚合块。
  - 证据 JSON 改为首次展开才渲染，并截断至 6KB（此前 38 条写入约 250KB DOM）。
  - 边点击后把关系表对应行 `scrollIntoView`。
  - 状态文案区分「预算截断」「局部视图边界」「Rule 范围不足」。
- `static/architecture-workbench.css`：`.ew-slice` 样式。

一致性：

- `static/mermaid-viewer.js` 引用统一 `v=3`（`allocation.html` / `graph.html` / `architecture.html`）。
- `base.html`：内联空 favicon，消除每页 404 控制台噪声。
- `acceptance_pnl_formation.py` / `browser_acceptance.py`：改为读 `TM1_BASE`。

新增：

- `scripts/acceptance_workbench.py`：37 项断言式浏览器验收。
- `scripts/perf_workbench.py`：6 类查询的冷/热性能测量。
- `tests/test_engineering_workbench.py::test_view_boundary_not_confused_with_budget_cut`。
- `docs/` 下 5 份文档。

### 2.3 未改动（有意保留）

图查询内核数据结构、工作区 Schema、Rule 语义解析、源码组件、代码模板引擎、分摊引擎、Mermaid 多实例机制。

## 3. 验收结果摘要

| 项 | 结果 |
|---|---|
| 全量 pytest | **923 passed / 0 failed / 0 skipped**，157s |
| 工作台专项 | 27 passed |
| 浏览器验收 | 4 个脚本全绿（工作台 37 项、主流程、PnL、分摊） |
| 真实模型查询 | 6 类，热态 107–210ms，冷索引 724ms |
| 正式库哈希 | 与本轮开始时完全一致 |

明细见 `VALIDATION_REPORT.md`。

## 4. 复跑方式

```bash
# 服务（只读本地快照）
PYTHONPATH=src .venv/Scripts/python.exe -m uvicorn tm1_insight.api.app:app --host 127.0.0.1 --port 8011

# 测试
PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q

# 浏览器验收（真实 Chrome，离线）
TM1_BASE=http://127.0.0.1:8011 .venv/Scripts/python.exe scripts/acceptance_workbench.py
TM1_BASE=http://127.0.0.1:8011 .venv/Scripts/python.exe scripts/browser_acceptance.py
TM1_BASE=http://127.0.0.1:8011 .venv/Scripts/python.exe scripts/acceptance_pnl_formation.py
TM1_BASE=http://127.0.0.1:8011 .venv/Scripts/python.exe scripts/acceptance_allocation.py

# 性能
TM1_BASE=http://127.0.0.1:8011 .venv/Scripts/python.exe scripts/perf_workbench.py warm
```

## 5. 下一轮入口

见 `NEXT_SPRINT_RECOMMENDATIONS.md`。最优先仍是：草稿 Cube 与真实模板的绑定、外部数据源节点、工作区资产导出。

## 6. 边界声明

- 未连接任何 TM1 Server，未读取业务 Cell 数据，未执行 TI/MDX。
- 未修改正式采集库，未删除 WAL，未触碰 `collections/`。
- 未引入任何 AI / 遥测 / 外网调用。
- 提交前已确认工作区目录属于本地用户数据、不入库。
