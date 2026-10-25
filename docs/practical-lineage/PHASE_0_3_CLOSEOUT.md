# Phase 0–3 收口核验

日期：2026-10-24。本轮接续已授权范围，不进入 Phase 4。目标是让 Cube 关系、独立写入点和导出始终属于同一次查询；不改解析语义。

## 差距及最小修复

复查 cube-lineage.js、workflow.py、Workbench 写入证据接口、Workflow fingerprint/cache、只读工作台及既有测试。源/目标切面继续使用原 Calculation read_nodes 与 coordinate_mapping；共同读写不升级为值流。

发现并修复两处展示一致性问题：

1. 旧查询已失效，但其非 AbortError 迟到时仍能覆盖新查询/取消状态。异常路径现在也核对 generation。
2. 完成查询后仅修改输入框，导出标题会错误使用未提交的对象名；查询过程中修改输入也会污染摘要。现在结果摘要、结构链接、Markdown 入口使用本次成功查询捕获的名称。

## 本轮文件

- `src/tm1_insight/api/static/cube-lineage.js`：请求代次保护、成功结果身份。
- `src/tm1_insight/api/templates/cube_lineage.html`：资源版本 v4。
- `tests/test_cube_lineage_ui.py`：实际控制器配合延迟 fetch 的 Node 行为测试，覆盖迟到成功、迟到错误、取消、未提交输入及导出一致性。
- `tests/test_workflow.py`：合成数据库源码/DataSource 元数据变化，旧 review/export/evidence 返回 409，新任务不复用缓存，旧结果文件哈希不变。
- 本报告。

## 浏览器及数据证据

仅使用 8807 隔离合成模型。实际输入 Not_Queried 而不提交后点击导出，下载 Markdown 仍为 `入口：Cube_B`。不是仅对导出函数做字符串检查。

实际展开 Cube_A → Cube_B，选择 Multiple：data:1:72 的 a*2 保留 Cube_A data:1:3 静态读取依赖；data:1:121 的 vUnknown 来源仍未确认，目标 Region=Member2 / Measure=Member1；没有继承前一写入的来源。Year=pYear 保持动态。

控制台错误 0；历史隔离服务请求日志中的 workspace 写请求 0。合成 DuckDB SHA256 与浏览器前基线相同：117CC5015D95B310268008714B9A385BD6267AE132FDF4F65BFE0F16115D9E33。

产物：`<local-acceptance>/phase03-closeout/`，包含 Cube-Lineage.md、cube-independent-writes.png、verification.json。

## 测试

运行器：`.venv\Scripts\python.exe scripts/run_offline_tests.py`（临时用户目录，阻断外网）。

- `-q tests/test_cube_lineage_ui.py tests/test_workflow.py`：28 passed, 1 warning，6.30s。
- 全量 `-q`：1120 passed，0 failed，1 warning，122.99s。警告为既有 Starlette TestClient/httpx 弃用提示。
- `node --check src/tm1_insight/api/static/cube-lineage.js` 与 `git diff --check` 通过。

## 边界与安全

不增加后端端点、解析器或数据库结构。模型失效仍依赖现有数据库/WAL 文件时间和大小 fingerprint，不宣称内容寻址或对人为保留文件属性的替换提供保证。本轮验证的是正常源码/元数据更新路径。

仅合成测试，不是企业真实模型验收；静态读取依赖不证明运行结果。新测试中的数据库更新全部发生在临时 fixture，正式 collections、Snapshot、DuckDB/WAL 未触碰。

分支 codex/canvas-excellence-04，HEAD 24ef873c24c75a6042f068330914526dadca69b6；保留全部原有未提交改动，无提交、推送、合并。后续优先由用户验收 Phase 0–3；不自动扩大到 Phase 4。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
