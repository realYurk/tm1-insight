# UI 实施报告

2026-10-22 · `codex/canvas-excellence-04` · 基线 `0f79bcf`。本轮未提交、推送、合并或发布。

## 结果

采用“主画布 + 按需资源栏 + 两层 Inspector + 单一创建入口”。保留现有美术、TI / Rule / 读写切换、拖线实现、工作区 v3、模板和后端分析。不是重写计算平台，也没有将旧能力替换成假接口。

默认无对象时显示开始探索空态，既不自动选择技术对象，也不伪造业务图。明确选对象后显示有向局部图。点击 TI 自动展示现有 writes API 的操作与关键切面；完整源码和证据进入第二层。点击 Rule 边展示相关规则数量、目标区域和已确认来源，保留不完整坐标和表达式边界。

## 修改文件

| 文件（均相对项目根） | 变化 |
|---|---|
| src/tm1_insight/api/templates/architecture_workbench.html | 单一创建菜单、空态、快捷搜索、折叠筛选、低频操作移入更多菜单 |
| src/tm1_insight/api/templates/architecture.html | 引入新的展示组件，更新本地静态资源版本 |
| src/tm1_insight/api/static/canvas-experience.js | 共享两层 Inspector 和事实摘要，不做解析 |
| src/tm1_insight/api/static/architecture-workbench.js | 最近访问、空搜索、系统对象显示过滤、摘要接入、创建动作、手工坐标保持、关闭不丢选择 |
| src/tm1_insight/api/static/canvas-layout.js | 默认分层、TB、稳定排序、SCC 成员分配及避免组件重叠 |
| src/tm1_insight/api/static/canvas-graph.js | 关闭 core 点击背景、TI 图标、方向保存、减少动画 |
| src/tm1_insight/api/static/canvas-shell.js | 收起状态、创建菜单、更多菜单 select 交互与 HUD 定时器清理 |
| src/tm1_insight/api/static/canvas.css | 摘要层次、空态、紧凑工具栏、明确 Grid 子项归属 |
| tests/test_canvas_ux.py | 5 个纯 JS 布局用例 |
| scripts/run_offline_tests.py | 可重复的隔离用户目录与禁外网 pytest 入口 |

另交付本目录五份文档。没有改 Python 分析模块、API 数据契约、模板生成算法、正式数据库或 WAL。

## 实际发现并修复的交互故障

浏览器验收发现两侧隐藏后，CSS Grid 自动放置会把画布挤进预留的零宽列。已为资源栏 / stage / Inspector 明确指定列，并补齐“双侧关闭”组合，实测画布占满工作区域宽度（1280 窗口内，工作区域及 stage 均为 1048px）。

创建关系表单有嵌套 details，按字段直接取最近 details 会把外层一起隐藏。已修复为展开所属顶层创建段及内部段。CSV 表单定位改为滚动到该段起点；没有为测试强行展开所有表单。

## 浏览器验收：真实点击，数据全部合成

隔离服务绑定 127.0.0.1:8804，专用测试用户目录，模型连接限制为该私有目录且 read_only。没有打开用户现有真实模型服务。

已实际操作：

- 默认空画布、资源栏及 Inspector 收起。
- 搜索 Cube_B，无默认第一项选中；打开 Cube_B 查看局部图与摘要。
- 点击 Rule 连线，看到 1 条相关 Rule、目标 Member1 区域、来源 Cube_B；概览与证据来回切换。
- 点击候选连线再进入 Load，看到 Cube_A 读取、Cube_B 写入、覆盖数值、运行时坐标；未把未知来源写成已确认传输。
- 关闭详情、实际拖动节点、保存和刷新恢复；没有清空选择或重新生成虚假关系。
- 通过可见“＋ 创建”直接建立 UX Target Draft，填写 Year / Region / Measure，保存为未部署草稿。
- 声明 Synthetic_Input.csv 表头，解析并保存 Schema；未打开文件、读取数据行。
- 创建 Schema → Cube 草稿的设计关系，保持“设计 · 未部署”标签；未执行生成或部署。
- 关系表切换 RULE_REFERENCE / TI_CANDIDATE / 全部，结果随筛选变化。
- LR / TB 切换、自动布局、适应画布。
- 浏览器控制台检查未见 error。

截图位于本机私有验收目录 `canvas-ux-04`，最终截图名 `06-final-workbench.png`。全部是合成模型，未把企业模型截图加入仓库。没有制作伪造的“重构前截图”；旧版问题以前端源码及 Git 基线为证据。

## 自动化结果

基线：1093 passed，0 failed / skipped。

专项：32 passed（新布局测试 + 原工作台契约测试），1 条既有 Starlette 弃用警告。

全量：1098 passed，0 failed / skipped，1 条既有 Starlette 弃用警告。耗时约 140 秒。

可重复命令：

```powershell
.\.venv\Scripts\python.exe scripts/run_offline_tests.py -q tests/test_canvas_ux.py tests/test_engineering_workbench.py
.\.venv\Scripts\python.exe scripts/run_offline_tests.py -q
node --check src/tm1_insight/api/static/canvas-experience.js
node --check src/tm1_insight/api/static/architecture-workbench.js
git diff --check
```

Node 是开发测试工具，不是 Portable 用户运行依赖。布局测试覆盖高扇出、120 节点、汇聚/分叉、LR/TB、自环、SCC、输入顺序稳定性及空图。原 `scripts/acceptance_canvas.py` 未在本轮执行，其模式按钮操作需要迁移，不能将历史记录算作本轮通过。

## 性能、兼容和安全

纯布局合成测试：120 节点 / 119 边，200 次平均约 0.38ms。此数字不含 API 分析、Cytoscape 渲染和浏览器帧时间，不等同于完整页面性能承诺。

继续使用已 vendored 的 Cytoscape 和静态资源打包规则，无 CDN、无新增运行依赖。旧路由、Workspace 旧版本校验、模板生成与导出保留。内部 design.mode 没删除，只隐藏面向用户的复杂顶层切换。

未连接 TM1 / 内网、未执行 TI / MDX、未读 Cube Cell、未打开或覆盖正式 DuckDB/WAL。测试只写隔离合成库与测试工作区文件。未重新构建或发布 Portable，未修改启动脚本。

## 限制与后续

- 本轮没有企业真实模型验收，不能宣称所有大模型交互已验证。
- 源切面、动态坐标和 Data 行变量缺证据时仍未确认；没有扩大后端语义。
- 系统对象过滤在客户端分页后执行；需要服务端先过滤再分页。
- Rule 搜索当前按所属 Cube 定位，不是独立 Rule 资产目录。
- 新增节点的增量布局仍有进一步优化空间；保留既有手工坐标，但不承诺任意手工布局下每条边都朝右。
- 既有拖线和模板生成没有重写；本轮没有新增一次完整拖线生成及运行数值验收，不声称代码草稿可直接投产。
- 创建 CSV 的测试包含键盘激活解析/保存；不是自动读取文件。SQL 创建未添加占位假入口。
- 尚未增加完整键盘选节点导航与创建菜单焦点闭环；后续按交接提示完善。

下一步最高价值：保持本轮视觉体系，补齐服务端目录过滤与摘要请求治理，并迁移可见创建入口的端到端浏览器门禁；复用现有工作区、校验和生成器，不新建第二套系统。
