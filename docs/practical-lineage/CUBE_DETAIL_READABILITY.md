# Cube 血缘：关系表与切面详情可读性修复

日期：2026-10-25。接续 Phase 0–3 的已授权闭环，仅改善 Lineage & Relationships / Architecture Explorer 的展示与操作，不进入 Phase 4。

## 问题与复用

前轮实际截图中，窄屏六列表格把源/目标切面挤成细长文本；展开证据原本位于 colspan 表格行中，受同一表格宽度和滚动限制。复查 cube-lineage.js、cube-lineage.css、cube_lineage.html、原 Calculation 写入证据接口及既有测试，确认后端事实已经足够，不需要新解析器或新端点。

## 实际修改文件

- `src/tm1_insight/api/static/cube-lineage.css`：关系表最小宽度 1040px，仅表格容器横向滚动，来源和目标 Cube 两列固定；切面详情使用独立宽度，窄屏切为单列。样式仅限 Cube 血缘页。
- `src/tm1_insight/api/static/cube-lineage.js`：详情移到表格下方独立区域；按钮支持重复点击关闭，只展开一个关系；切换关系保留各自已核对的独立证据；打开时定位详情，关闭按钮将焦点还给原关系按钮；重新查询清空旧面板。解析与导出投影不变。
- `src/tm1_insight/api/templates/cube_lineage.html`：新增 cl-details 容器，关系表滚动区可键盘聚焦、有可读名称；资源版本 CSS v4 / JS v6。
- `tests/test_cube_lineage_ui.py`：扩展实际控制器 Node 行为测试，覆盖关闭/重开不重复、关系切换、关闭焦点、详情定位、查询切换清理；保留迟到响应、取消、导出对象一致性及动态 UNKNOWN 的原测试。
- 本报告。

## 浏览器验收与证据

仅使用 8807 隔离合成服务，无真实企业模型；旧 8806 服务在环境恢复后已未运行，未将其当成可用服务。恢复的 8807 仍使用原脚本的外网阻断和 Store 只读保护。

- 640×800：页面 clientWidth/scrollWidth = 625/625；关系表容器宽 521、内容宽 1040；详情宽 521，切面内容约 449.6；详情不在表格内，页面不横溢。
- 1280×800：页面 1265/1265；表格容器 961、内容 1040；单个展开关系、两个独立写入点。最终 computed style 确认来源列 position=sticky。
- 最终窄屏固定列复核：表格 scrollLeft=64 时，来源单元格左边界与滚动容器左边界同为 84，来源列没有随内容移出视野；页面仍为 625/625。测试后恢复默认视口。
- 再核对最终双固定列：来源与目标相对表格容器左边界分别是 0 / 160，两列 computed position 都是 sticky，避免来源固定后目标仍被遮住。
- 实际点击关闭后 openPanels=0；焦点是原“查看切面与证据”按钮，aria-expanded=false。重开后仍两个写入点，无重复内容。切换 Rule 后只有 Rule 关系展开，TI 面板隐藏。
- 合成 Multiple 的 data:1:72 保留 a*2 与 Cube_A data:1:3 的静态读取依赖；data:1:121 的 vUnknown 仍为未知来源。目标的动态 Year 与固定 Region/Measure 分开，未把共同读写升格为值流。
- RuleOutput 的裸 Member1 所属维度仍待确认；不因本次页面改造推断维度。
- 实际下载 Markdown，cube-lineage-review-1 不变，4 条关系、Multiple 两个独立写入点和已核对 Rule 证据均保留。第二个写入没有 source_reads。

前图：`<local-acceptance>/phase03-closeout/cube-independent-writes.png`。

本轮产物：同根目录 `cube-detail-readability/`，包含 final-details.png、narrow-details.png、browser-measurements.json、Cube-Lineage.md、safety-and-export.json 和 regression.txt。

## 测试与性能

`.venv\Scripts\python.exe scripts/run_offline_tests.py -q tests/test_cube_lineage_ui.py tests/test_readonly_report_view.py`：13 passed, 1 warning，最终专项复跑 3.09s。

首次全量 1119 passed / 1 failed / 1 warning，138.96s：测试进程已载入旧模拟 DOM，期间新增 scrollIntoView/focus 的控制器被动态读取，出现测试版本不一致。当前模拟 DOM 已补齐并通过上述专项；冻结控制器与测试后全量复跑 **1120 passed / 0 failed / 1 warning，125.93s**。首次日志保留为 regression-intermediate.txt，没有删除失败测试。`node --check`、`git diff --check` 通过，后者仅原有 workflow.py 的换行格式提醒。警告为既有 Starlette TestClient/httpx 弃用提示。

每条关系只新增一个空的隐藏 section；详情内容首次打开才构建，TI/Rule 仍按需读取，重开不重复构建、不额外发起分析。不改 40 Cube / 100 关系、80 写入 / 160 保留读取的原有预算。本轮未测大型真实模型 FPS。

## 安全、兼容与限制

未修改 Parser、Calculation、Rule IR、后台 API、数据库 schema、导出契约或任何正式 Snapshot/DuckDB/WAL。合成模型 SHA256 仍为 117CC5015D95B310268008714B9A385BD6267AE132FDF4F65BFE0F16115D9E33；请求日志 workspace 写入为 0。保留全部原有未提交修改；分支 codex/canvas-excellence-04，HEAD 24ef873c24c75a6042f068330914526dadca69b6，无提交、推送、合并。

静态依赖不证明运行结果；本轮不是企业真实模型验收。关系表窄屏需要自身横向滚动，详情则无需跟随表格滚动。下一步优先验收当前 Cube → 关系 → 独立写入点闭环，不自动扩大到新架构功能。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
