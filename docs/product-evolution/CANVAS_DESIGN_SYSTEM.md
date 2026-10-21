# Canvas Design System — 精密工程风格设计系统

实现文件：`src/tm1_insight/api/static/canvas.css`（唯一权威，令牌 + 外壳 + 组件）。
范围：仅架构沙盘工作台；不改动全局 `style.css`，其余页面不受影响。

## 1. 设计语言

**Precision Engineering**：克制、冷静、精确。深海军蓝应用栏 + 浅色画布 +
中性面板；无霓虹、无渐变滥用、无玻璃拟态。高级感来源：稳定层级、统一控件高度、
一致的 4px 间距节奏、克制的颜色语义。

## 2. 令牌（`--cx-*`）

| 类别 | 令牌（节选） |
|------|------|
| 色 | `--cx-accent #3556d4`、`--cx-canvas-bg #f7f9fc`、`--cx-canvas-dot #e5ebf3`、`--cx-chrome #182035`、`--cx-text #1c2333`、`--cx-text-2/3`、`--cx-border/-2`、`--cx-danger/--cx-warn/--cx-ok` |
| 边语义 | `--cx-edge-candidate #64748b`（虚线）、`--cx-edge-rule #2563eb`（实线）、`--cx-edge-design #b45309`（虚线） |
| 间距 | `--cx-s1..s6 = 4/8/12/16/24/32px` |
| 控件 | `--cx-ctl-h 30px`（全部按钮/输入/选择统一高度）、`--cx-appbar-h 48px`、`--cx-rail-w 272px`、`--cx-inspector-w 336px` |
| 字体 | `--cx-font` 系统栈；`--cx-mono` Cascadia/Consolas（代码） |
| 圆角/阴影 | `--cx-radius 8px`、`--cx-radius-sm 6px`、`--cx-shadow-1/2` |

## 3. 空间结构（Canvas-first）

```
┌──────────────────────────────────────────────────────────┐
│ App Bar 48px：品牌 · 探索/设计分段 · 上下文芯片 · 工作区 · 保存 · ⋯ │
├──────────────────────────────────────────────────────────┤
│ Status Line 22px：状态消息 · 已选 N 个对象                        │
├──────────┬────────────────────────────────┬──────────────┤
│ Rail     │ Toolbar（适应/布局/隐藏/恢复/清空）│ Inspector    │
│ 272px    │ ┌────────────────────────────┐ │ 336px        │
│ 对象搜索  │ │        Canvas（点阵底）      │ │ 仅选中时展开  │
│ 探索范围  │ │  图例(左下,可折叠) HUD(右下) │ │              │
│ 模块     │ └────────────────────────────┘ │              │
│ 设计草稿  │ Dock：关系证据 / 研究笔记（默认收起）│              │
└──────────┴────────────────────────────────┴──────────────┘
```

- 工作台独占视口：`body:has(.cx-root)` 锁死 `.main-area/.content` 高度，页面不滚动。
- 低频操作（另存/导入/导出/打开已保存工作区）收进 `⋯` 溢出菜单。
- 底部 Dock 取代旧的常驻大 textarea；研究笔记（MDX/备注）为独立页签。
- Inspector 空状态显示引导文案；`Esc` / `Ctrl+S` 全局快捷键。

## 4. 节点与边

- **节点**：Cytoscape 内联 SVG 立体 Cube（蓝=真实 Cube、琥珀=草稿、紫=CSV 来源、
  灰=技术对象），名称白底衬垫，选中 2px 蓝框，悬停浅蓝框 + 提示条。
- **边**：候选=灰虚线、Rule=蓝实线+tee 箭头、Feeder=点线、设计=琥珀虚线；
  多关系聚合显示 `n TI`；平行边按 36px 控制点间隔分层；自环 loop-sweep。
- 命中区：`overlay-padding: 13px`，1px 细线周围有透明命中带。
- **语义缩放**：zoom < 0.55 时自动隐藏全部边标签，恢复倍率后还原。

## 5. 交互状态

按钮/输入均有 Default/Hover/Active/Focus-visible/Disabled；
保存状态有 `dirty/saving/saved/error` 四态指示（应用栏内联，不用弹窗）；
Reduced Motion 下全部过渡关闭。

## 6. 响应式

- ≤1500px 收窄 rail/inspector；≤1100px 打开详情时自动隐藏 rail；
- ≤820px 高度压缩 Dock 高度与工作区名宽度；
- 1366×768 实测：无页面滚动、可收起资源栏、无节点碰撞（`acceptance_excellence.py`）。
