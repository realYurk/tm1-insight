# Architecture Canvas — UI Polish 2.0 交付报告

日期：2026-10-22 · 分支：`codex/canvas-excellence-04` · 全部基于真实代码修改并实测截图。

## 一、修改文件清单

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `src/tm1_insight/api/static/canvas.css` | ① 顶栏令牌 `--cx-chrome` 深色系（#182035）→ 浅色白底体系，新增 `--cx-chrome-border`；② appbar 高度 48→44、加底部细线；③ 模式切换/工作区输入框/保存状态全部换浅色令牌；④ 边语义色变量降饱和；⑤ Inspector 重写：新增 `.cx-inspector-head-main`、`.cx-inspector-sub`、`.cx-badge`（6 种类型徽章）；摘要行改「小标签+值+虚线分隔」层级，去掉顶部粗横线堆叠；tabs 改下划线式轻量 tab | 顶栏黑色是用户最不满意的点；右栏表单堆砌缺层级；统一设计语言 |
| `src/tm1_insight/api/templates/architecture_workbench.html` | 品牌图标描边色适配浅底；“更多”按钮移除内联深色样式 | 深色残留清零 |
| `src/tm1_insight/api/static/canvas-graph.js` | ① 节点卡片：高度 44→42、边框 #cbd5e1→#e2e8f0、图标 22→18px、文字宽 150→165；② 选中/hover 态改 1.5px 细边+微蓝底（#f6f9ff），去 2px 硬边框；③ 边宽 1.8→1.4、箭头缩小、标签字号 10.5→9.5 且颜色更浅；④ **边标签默认隐藏，hover/选中才显示**（样式层 class 驱动）；⑤ 边色整体降饱和（如 Rule #2563eb→#5b7fd6）；⑥ cardW 公式收紧（上限 240→210） | 节点放大后“傻大粗”、线条标签偏多偏吵 |
| `src/tm1_insight/api/static/canvas-layout.js` | `nodeWidth` 与 cardW 同步为 `60+len*6.0, max 210` | 布局间距必须与视觉宽度一致，否则 Fit 后挤压/碰撞 |
| `src/tm1_insight/api/static/canvas-experience.js` | `mount()` 支持 `meta` 参数：Header 显示类型徽章 + 副标题；语义零改动 | 右栏 Header 分区 |
| `src/tm1_insight/api/static/architecture-workbench.js` | ① `panel()` 透传 meta；② Cube 详情重组为四段：核心关系（输入/输出/关联TI + 关联关系折叠）→ 结构信息（维度数 + 顺序折叠）→ 操作入口（h3 分组）→ 源码；③ 关系详情标题保留类型、来源→目标进副标题 | 右侧像后台表单一节节堆，无层次 |
| `scripts/acceptance_excellence.py` | 「低倍率隐藏边标签」断言更新为「默认隐藏、hover 显示」（新策略严格更强） | 降噪实现从数据驱动改为样式驱动 |

## 二、缩放丑态根因说明

实测几何：节点模型尺寸恒定（210×42），zoom 1.5→0.6→1.0 往返后 rendered 尺寸精确还原（213.5≈210×zoom），**宽高比无变形**——底层坐标没有 bug。放大后的“丑”来自三个视觉层问题，均已修复：

1. 厚重实色边框（#cbd5e1 1px 在放大后显得笨重）→ 更浅边框 + 选中态 1.5px 细边；
2. 图标 22px 贴左、文字固定 margin，长卡片右侧大片空白 → cardW 上限收紧至 210、文字宽 165 补齐；
3. 大尺寸下 22px 图标与 44px 高度比例失衡 → 图标 18px、高度 42px，比例更协调。

## 三、修改前后对比

- **顶栏**：深黑大块（#182035，按钮/输入框全部深色内联样式）→ 白底细线轻条，与左右面板同族；高度 -4px。
- **节点**：白块+厚边框+图标失衡 → 轻卡片：浅边框、18px 图标、完整名称、微蓝选中态、hover 背景反馈。
- **右栏**：裸 stat 行从上堆到下 → Header（名+类型徽章+副标题）→ 核心关系 → 结构信息（默认折叠）→ 操作区块；摘要行小标签+虚线分隔。
- **画布**：虚线上「2 TI / Rule」标签糊满 → 默认零标签，hover/选中才出现；线更细（1.4px）、色更轻；画布底色/点阵更浅。
- 截图：`logs/polish2_before/`（3 张基线）vs `logs/polish2_after/`（3 张改造后）。

## 四、验收结论（全部实测）

| 验收标准 | 结论 |
|---|---|
| 顶部不再是黑色 bar | ✅ 白底轻条，深色残留 grep 清零 |
| 节点放大后不丑 | ✅ 150% 实测截图：轻边框小图标完整名称，无空洞 |
| 右栏不再像后台表单 | ✅ 四段结构 + 徽章 + 折叠 |
| 页面更轻更干净 | ✅ 边标签默认隐藏、线条变细变浅 |
| 中间画布是主角 | ✅ 顶栏 -4px、点阵更浅、噪音减少 |
| 缩放往返不变形 | ✅ 几何实测精确还原 |

## 五、回归验证

- pytest：`test_canvas_ux + test_engineering_workbench` 33 passed；
- 浏览器验收：acceptance_pointer / acceptance_canvas / acceptance_workbench / acceptance_design / acceptance_excellence **全部通过**（含布局指标 overlap=0、clipped=0、无脚本错误）。

## 六、已知待优化

1. 左侧全局导航（style.css 体系）仍偏深，与画布工作台浅色系的统一需另一轮（跨页面影响，本轮未动）；
2. 路径聚焦高亮（点节点淡化无关对象）已有关联关系折叠，但画布级 dim 联动（`cn-dim` 类已存在）尚未接到普通选中流程；
3. 徽章色板目前 6 种，后续如新增对象类型需同步 `TYPE_BADGE`；
4. 图标在小缩放（<60%）下识别度一般，可考虑极低倍率切换为纯色小方点（语义缩放第二级）。
