# Product Quality Report — Canvas Excellence Sprint

日期：2026-10-22 · 分支：`codex/canvas-excellence-04` · 基线 `732859a`

## 交付内容

**核心转变：从"表单和页面为中心"到"架构画布为中心"。**

1. **应用外壳**（`canvas.css` + `canvas-shell.js` + 重构的 `architecture_workbench.html`）：
   应用栏 / 状态行 / 资源栏 / 画布 / Inspector / 底部 Dock 六区结构，
   工作台独占视口、页面零滚动；低频操作收进溢出菜单；统一控件高度与 `--cx-*` 令牌。
2. **布局引擎**（`canvas-layout.js`）：辐射 + 分层 + SCC 环处理 + 重心排序 + 分栏，
   客观指标重叠 0 / 裁切 0 / 宽高比 1.17（改造前：一字长蛇阵 + 全标签重叠）。
3. **画布增强**（`canvas-graph.js`）：语义缩放、Esc 取消拖线、拖线目标高亮、
   空释放明确提示、背景右键菜单（新增草稿/自动布局/适应）、程序化视口保护、
   边命中区 13px、标签白底衬垫。
4. **外壳交互**：Esc/Ctrl+S 快捷键、Dock 页签与折叠、图例折叠、保存四态指示、
   缩放 HUD、资源栏折叠记忆、多选计数。
5. **修复**：资产导出 >60 项 422 裸奔 → 可读提示；测试资产污染去重（先备份）。

## 验证结果（全部真实执行）

| 项 | 结果 |
|---|---|
| pytest 全量 | **1093 passed / 0 failed**（135.9s） |
| acceptance_canvas（画布+拖线+保存恢复+自环平行边+复用） | 30 项全过 |
| acceptance_pointer（真实鼠标 10 项） | 全过 |
| acceptance_workbench（语义与证据 37 项） | 全过 |
| acceptance_design（设计模式 32 项） | 全过 |
| acceptance_assets（资产闭环 17 项） | 全过 |
| acceptance_pnl_formation / acceptance_allocation | 全过 |
| acceptance_excellence（布局指标/键盘/Dock/紧凑窗口 16 项，新增） | 全过 |

截图证据：`logs/round0/`（Before 3 档）、`logs/browser_acceptance/50-56、60-62`（After 全流程）。

## 自评（每项 0–10，附依据）

| 维度 | 分 | 依据 |
|---|---|---|
| 1 Visual Hierarchy | 8.5 | Before/After 截图对比：4 行控件压顶 → 48px 应用栏；画布高度约 400px → 约 850px；Inspector 仅选中时出现 |
| 2 Graph Readability | 8 | 18 节点辐射图重叠 0、裁切 0、宽高比 1.17（客观脚本）；标签白底衬垫 |
| 3 Edge Interaction | 8 | 13px 命中带 + 悬停加粗 + 提示条；四类边线型+颜色+标签三重区分；聚合 `n TI` 可点开 |
| 4 Layout Quality | 8 | 布局引擎按图形态选择策略；环不强行 DAG；用户视口不被覆盖 |
| 5 Interaction Continuity | 8 | 详情开合不丢缩放（验收断言）；保存恢复逐点一致；安定窗口自动重适配 |
| 6 Design Workflow | 8.5 | 真实拖线→映射→生成→STALE→Blueprint 全链路验收通过，全程不离开画布 |
| 7 Code Generation Safety | 9 | 本轮未改 CodeGen；1093 测试含变量映射与清空范围两条红线；生成面板标注未部署/未验证 |
| 8 Asset Reuse Integration | 8 | Blueprint→画布→再导出→导入全通过；新加 60 上限可读提示 |
| 9 Performance | 7 | 18-50 节点交互流畅（Cytoscape canvas 渲染）；100+ 节点未做系统压测，超 120 节点/300 边有预算护栏优雅拒绝 |
| 10 Product Finish | 8 | 统一令牌/控件/状态/空态/快捷键；深色应用栏与浅色画布一致成体系；无浏览器默认控件突兀感 |

**无低于 7 分项。** 第 9 项（性能）是最薄弱处：已有预算护栏与 canvas 渲染，
但缺少 100 节点级的系统测量（见 NEXT_PRODUCT_DECISIONS）。

## 已知限制（不伪造完成度）

- TI 对象视图（`objects` 图层）里 TI 仍是灰色小节点 —— 这是"高级视图"的既定语义，
  默认 Cube 主干不受影响。
- 无撤销（Ctrl+Z）、无力导向布局、模块折叠仅视觉折叠。
- 未做 100 节点性能基准；Portable 构建本轮未重新打包（静态资源清单需更新
  `canvas.css/canvas-layout.js/canvas-shell.js` 三个文件后重跑 `make_release.py`）。
- 公开 GitHub 历史中的企业对象名问题沿用 `docs/security/PUBLIC_REPOSITORY_AUDIT.md`，本轮未处理。

## 数据安全

- 未连接 TM1 / 未读 Cell / 未执行 TI/MDX / 未改正式 DuckDB/WAL / 未引入 AI。
- 分支开发，master（8ef6d67）未动；无强推、无历史改写。
- 测试资产清理前已整目录备份（`logs/backup-assets-20261022/`）。
