# Canvas UX Audit — 改造前问题与组件审计

日期：2026-10-22 · 分支：`codex/canvas-excellence-04` · 基线：`codex/engineering-asset-3` (732859a)

## 审计方法

- 真实 Chrome（Playwright + 本机 chrome.exe）打开 `/architecture?view=workbench`，
  以 Demo 模型（3,338 Cube / 3,437 TI）中 `General Ledger`（中心 + 17 邻居，18 条关系）为标准用例。
- 三档分辨率截图：1920×1080 / 1600×900 / 1366×768（`logs/round0/`）。
- DOM 与 JS 契约审计：提取 `architecture-workbench.js` 全部 `$('ew-*')` 依赖。

## 改造前问题清单（截图 `logs/round0/workbench_1920.png` 为证）

| # | 问题 | 证据 | 严重度 |
|---|------|------|--------|
| A1 | 页面信息层级失控：页面标题、两个视图入口、模式切换、整排保存按钮、图例共 4 行 UI 压在画布上方 | 1920 截图顶部 ~170px 全是控件 | 高 |
| A2 | 画布被挤压：有效画布高度仅约 400px（1080 高的屏幕） | 同上 | 高 |
| A3 | 布局呈"一字长蛇阵"：17 个周边 Cube 排成底部一行，关系从中心呈扇形放射 | 同上画布区域 | 高 |
| A4 | 节点名称相互重叠：底部一行标签完全不可读 | 同上 | 高 |
| A5 | 自环叠在节点上 | GL 顶部 | 中 |
| A6 | 多个滚动容器（页面 / 左栏 / 右栏 / 下方表格）各自滚动 | — | 中 |
| A7 | 操作形式不统一：按钮 / 原生 select / 大 textarea / details 混排，无统一控件高度 | — | 中 |
| A8 | 低频操作（另存 / 导入 / 导出 / 打开工作区）常驻主界面 | 保存栏 7 个控件 | 中 |
| A9 | MDX / 研究笔记以巨大 textarea 永久占据画布下方 | — | 中 |

## 组件审计

| 组件 | 状态 | 处置 |
|------|------|------|
| `canvas-graph.js`（Cytoscape 封装，624 行） | 语义正确（候选/Rule/Feeder/设计四类边、自环、平行边、聚合标签） | 保留；补语义缩放、Esc 取消拖线、程序化视口保护 |
| `architecture-workbench.js`（762 行） | 业务编排完整，依赖 66 个 `ew-*` id | 保留 id 契约；去掉与外壳重复的绑定 |
| `architecture-workbench.css`（27 行 minified） | 与新结构冲突 | 由 `canvas.css` 取代（旧文件保留但不再被 workbench 引用） |
| `style.css` 设计令牌 | 已有 `--accent/--border/--text` 等基础 | 画布工作台建立独立 `--cx-*` 令牌体系，不动全局 |
| 布局 | breadthfirst 退化为底部一行 | 新建 `canvas-layout.js`（见 GRAPH_LAYOUT_REPORT） |
| `workspace-persistence.js` / 工作区 schema v3 | 正常 | 未改 |
| CodeGen / Preflight / Blueprint 后端 | 正常 | 未改（回归 1093 passed） |

## 数据安全基线（Round 0 冻结）

- 未连接 TM1 Server，未读取 Cell，未执行 TI/MDX；Demo 离线模型。
- 正式 DuckDB/WAL 未触碰；工作区仍写入独立用户目录。
- 资产库中 80 个历轮验收产生的合成 Blueprint（名称 "X" ×32、"Production Volume Load" ×32、"Canvas Reuse" ×16）
  在整目录备份至 `logs/backup-assets-20261022/` 后去重为 3 个；导出路径增加 60 上限的可读提示。
