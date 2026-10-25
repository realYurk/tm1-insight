# Phase 3：只读模块概览与报告阅读适配

日期：2026-10-24。按用户“继续”接续 Phase 0/1/2。只改展示层，不新建分析引擎、设计器或远程连接。分支 `codex/canvas-excellence-04`；此前全部未提交成果保留。

## 实际问题与复用
- 原 Functional Flow 已有对象/动作摘要表，但位于自绘大图下方，且随图视图隐藏。现在把已有表格放到默认主体，图变成折叠辅助。
- 共享 Mermaid CSS 只在 architecture 页面加载，Cube/TI 页面缺少同样的容器约束。抽为 mermaid-viewer.css，在 base 中共享，不对全局 SVG 强制缩放。
- 原 viewer 拦截所有滚轮；改为普通滚轮阅读页面，Ctrl/Meta 滚轮才缩放。
- 适配只在初次渲染发生，隐藏容器/窗口变化可能破坏视口。现在隐藏时不覆盖 fit，适配模式自动响应 resize，手动缩放/平移不被 resize 重置。
- 超宽图受 0.15 最小缩放限制无法完全适配；降低为 0.01，仍可用 1:1 / 平移看细节。主交付仍是表格。
- 实测 Mermaid 10 渲染失败会在 body 留下额外错误 SVG。清理仅针对本次 renderId 对应的临时容器，其他 viewer 不受影响。

## 修改文件
- `src/tm1_insight/api/static/functional-flow.js`：复用 TM1Workbench.flowTables，表格优先；详情独立于图；默认不打开详情；图默认折叠；24 对象/40 动作以上保留表格而不绘图；Mermaid 实例随切换/离页释放。
- `api/static/functional-flow.css`：模块详情和容器边界，移出共享 Mermaid 样式。
- 新 `api/static/mermaid-viewer.css`：宽度约束、单一外层 transform、工具栏换行、全屏、失败回退容器。
- `api/static/mermaid-viewer.js`：滚轮行为、fit/resize、隐藏保护、临时错误节点清理与 ResizeObserver 释放。
- `api/templates/base.html`：共享样式；仅把业务架构链接从画布改为现有模块入口。没有重做导航。
- `api/templates/architecture.html`：标明辅助只读画布，模块页签改为“对象与动作 / 范围与边界”，更新资源版本；Cube/TI 模板仅更新共享 viewer 版本。
- 新 `tests/test_readonly_report_view.py`：页面入口/共享样式兼容，真实 viewer 的模拟 DOM 行为测试（普通滚轮、显式缩放、超宽 fit、resize、隐藏、清理）。

未修改任何 Parser、Rule IR、Calculation DAG、索引图算法、正式数据库或导出 schema。原 workbench URL、历史工作区、代码生成和 API 保留。

## 实际浏览器验收
仅使用前轮隔离服务 8807 的合成数据，另开 8808 静态渲染故障 fixture（无数据库；完成后已停止）。

1. Load 模块默认显示 4 个对象 / 4 条动作；图默认折叠。对象详情可以在图关闭时查看，不强制打开图。
2. 页面表格与同任务原 Flow JSON 导出逐项核对：对象名集合、动作来源/标签/目标完全相同。该例 JSON 11028 字节；没有维护第二套事实生成器。
3. Cube_B 模块入口也实际打开：8 个对象 / 12 条动作，默认图关闭，无页面横向溢出。
4. 640px / 1280px 窗口下，clientWidth/scrollWidth 分别为 625/625 与 1265/1265。表格窄屏内部可横向滚动；页面本身不溢出。
5. 两种宽度下适配后的 SVG 均在 .mm-viewport 内。普通滚轮在图上使报告 scrollTop 从 1940 降到 1132，transform 保持完全相同，证明没有被强制变成缩放。
6. 独立超宽图 fixture 在 640px 时 fit scale=0.0657021；SVG 仍在容器内、页面不横溢。它是展示测试数据，不是 TM1 模型分析结果。
7. 故障 fixture 使用不完整 Mermaid：表格仍有 2 行、证据附录可读，局部回退为源码；修复后 body 无残留临时错误容器。没有伪造实际模型解析错误。
8. 已恢复浏览器 viewport 默认设置；模块页控制台没有错误。未宣称完成浏览器全屏专项或大型真实模型 FPS 验收。

验收产物目录：`<local-acceptance>/report-reader-phase3/`。
包含 module-tables-default.png、cube-module-tables.png、failure-fallback-table-readable.png、large-diagram-640-fit.png、browser-measurements.json、module-table-evidence.json、Flow-synthetic.json。

## 自动验证
`.venv\Scripts\python.exe scripts/run_offline_tests.py` 使用临时用户目录并阻断外网。
- `tests/test_human_workbench.py tests/test_functional_flow.py tests/test_cube_lineage_ui.py tests/test_workflow_review.py -q`：42 passed, 1 warning，8.20s。
- 新 reader 专项加原 Human/Functional Flow：28 passed, 1 warning，6.76s。
- 全量：1117 passed, 1 warning，142.15s。
- 清理渲染错误临时节点后 reader 专项：2 passed, 1 warning，1.11s；浏览器故障 fixture 也重新验证。
- 交付全量复跑 `-q`：1117 passed, 1 warning，120.50s。
警告为既有 Starlette/httpx 弃用提示。Node 语法检查与 git diff --check 通过（已有 CRLF 转换提示不影响结果）。

## 安全、兼容与限制
合成 DuckDB 浏览前后 SHA256 相同；没有工作区/设计保存请求。只读分析派生缓存仍在独立测试 home。未连接企业 TM1、未读取单元格、未执行 TI/MDX、未写正式 Snapshot/DuckDB/WAL、未上传企业数据；未提交、推送或合并。

页面仍使用原 Functional Flow / Architecture / Markdown / JSON / Mermaid 导出链，新增 CSS 不是新前端技术栈。图组件保持原 mount/getView/select/destroy 契约。

这是现有架构报告的可读展示投影，不是通用 Markdown 文件编辑/导入器。表格分页/作用摘要及助手折叠继续采用原引擎事实，未改善业务语义、未解决动态 vValue/未知维度归属，也未验证真实 BP 模型。

局部范围超过图预算时采用表格，不冒充全模型图；前端仍接收原 API 的有界对象集合，并非无限虚拟滚动。小合成模型不能证明大型企业模型的耗时或帧率。未重新构建 Portable，但未新增运行依赖。

下一步建议：在明确指定的本地只读快照上验证一个真实 Cube/TI 研究任务，优先补足具体来源/坐标证据；不再添加平行画布或通用解释引擎。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
