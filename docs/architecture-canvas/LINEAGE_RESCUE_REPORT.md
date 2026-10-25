# Cube Lineage Usability Rescue — 交付报告

分支：`codex/canvas-excellence-04` · 全量测试 **1140 passed** · 只用本地 demo 合成模型，未连接 TM1 Server，未读取业务数据。

## 核心原则的落实

**"用户不应该替解析器完成工作"**——本轮最大的行为变更：选中关系后软件**自动**读取本地 Snapshot 中已有的 TI 写入分析 / Rule 语义分析（复用现有 `/api/workbench/writes`、`/api/workbench/rules`，含缓存、预算、409 保护、取消），不再要求用户逐条点击"核对 TI / 核对 Rule"。

## A（未分析）与 B（已分析无法确认）的区分

- 旧行为：`未核对 23` 把"软件还没分析"当用户待办展示。
- 新行为：摘要列默认"选中后自动分析"；分析后显示已掌握事实（`3/3 个 TI 已分析 · 52 个写入点 · 156 个固定坐标`）；确实无法确认之处仅在详情内以"源切面：未确认"简短标注，附证据边界。覆盖统计移入二级区域，措辞改为"未分析（不代表无法确认，仅是尚未读取本地分析）"。

## 逐项验收

| 任务书条目 | 落实 |
|---|---|
| 二 · 首页简化 | 工具栏只留 Cube/方向/搜索/导出；核对预算、批量报告、覆盖状态、模块入口全部移入「分析范围与技术说明」折叠区 |
| 三 · 关系摘要 | 4 列：来源/目标/机制/关系摘要；摘要列展示对端机制、TI·Rule 数、分析后的写入点与切面事实；"共同读写已记录；值流未证明"等重复诊断列删除（证据边界保留在详情内） |
| 四 · 自动分析 | 打开详情自动分析该关系全部 TI / Rule；逐项失败降级（413 预算超限给出明确提示），不阻断其他项；缓存/409/取消语义与原来完全一致 |
| 五 · Rule 详情 | GL → Sys Definition BNK Dep Account Expense Config 实测：默认展示目标区域、DB 表达式、8 个 DB 源坐标（动态/固定 pill）、目标区域维度归属；Rule 原文与未确认项折叠 |
| 六 · TI 详情 | 默认展示写入方式/值表达式/目标切面（固定、动态、待确认分 pill）/源切面；"仅有声明或共同读写不能证明值依赖"只说一次，不重复十几次 |
| 七 · 噪声移除 | 原始 JSON、索引证据、分析限制全部进折叠 details；无灰色占位卡片堆砌 |
| 八 · Mermaid | 默认折叠；展开时**只画当前选中关系**（截图：GL → Sys Definition 单条边清晰可读）；无选中时全量图仍受 24 节点/30 边预算 |
| 九 · 核对负担 | "逐条核对"按钮删除；自动分析 + 二级批量研究保留 |
| 十 · 测试 | `test_cube_lineage_ui.py` 更新为新契约（5 列表、自动分析请求、只读端点断言、分析措辞）；全量 1140 passed |

## 修改文件

- `src/tm1_insight/api/templates/cube_lineage.html` — 首页结构重组，工具栏精简，二级折叠区
- `src/tm1_insight/api/static/cube-lineage.js` — 自动分析流程、关系摘要列、updateRow/updateCoverage 重写、Mermaid 选中联动、markdown 报告措辞（核对→分析）
- `src/tm1_insight/api/static/cube-lineage.css` — 提示/加载/二级区域样式
- `tests/test_cube_lineage_ui.py` — 新交互契约

后端 API 零改动（现有分析能力全部复用）。

## 修复过程中的真实 bug

1. `table.append(tr)` 重复调用导致每行渲染两次（harness 断言 `5!==3` 定位）。
2. 重写 `updateRow` 时丢失 `records` 定义，浏览器实测发现"自动分析未完成: records is not defined"。

## 已知边界

- 语义缩放/布局等画布能力不在本轮范围（禁止事项明确不开发新画布）。
- 长名称 Cube 在表格中的换行沿用现有 `overflow-wrap:anywhere`。
- 未提交；工作区同时含有上一轮 Canvas 5.0 / Polish 2.0 的未提交改动。
