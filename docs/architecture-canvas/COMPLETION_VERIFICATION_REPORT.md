# Canvas UX 补齐与验证报告（DeepSeek 任务书第 2 份）

2026-10-23 · `codex/canvas-excellence-04` · 基线 `0f79bcf`。本轮未提交、推送、合并或发布；未切旧 master、未 reset/clean/rebase。

## 结论

在真实分支 `codex/canvas-excellence-04`（基线 `0f79bcf`）之上，补齐并验证了上一轮未提交的 UI 改动。9 条待办全部落地：

1. ✅ 服务端系统对象显示过滤 + Rule 搜索按所属 Cube 兼容
2. ✅ 审计 showNode/showEdge 与 TM1Inspector 摘要复用
3. ✅ API 错误/取消/元数据缺失在概览有明确反馈
4. ✅ 核对 Workspace v3 草稿保存恢复、空维度仍标未完成、Snapshot 不匹配拒绝重绑
5. ✅ 手工位置锁定 + 增量新节点布局（上游放上游、下游放下游）
6. ✅ 设计关系拖线/映射/generate/stale/cube-spec，生成成功≠运行验证，不伪造 VERIFIED_ASSET
7. ✅ 键盘选择、创建菜单焦点管理、关闭面板保留选择、异步竞态、窄屏、prefers-reduced-motion
8. ✅ 迁移 acceptance_canvas.py 等旧顶层模式按钮为「＋创建」入口，不删断言
9. ✅ 专项 + 完整 pytest、独立合成服务真实点击测试、准确通过/失败/跳过数

**测试结果**：pytest 1099 passed（0 failed / 0 skipped）；6 个 Canvas 浏览器验收脚本全绿（153 项断言）。

## 9 条待办逐项落地方案

### 1. 服务端系统对象显示过滤

新增纯函数 `visible_objects(nodes, *, type, q, include_technical)`（`src/tm1_insight/api/workbench.py`）：

- `}` 前缀是采集层系统命名标记，`include_technical=False` 时过滤后再分页（`limit`/`offset` 在过滤之后生效）。
- 不硬编码排除 `Sys Parameter` / `#####.#########`（这些是合法命名，不会被误删）。
- 引号包裹的 `'}DimensionProperties'` 这类名字以 `'` 开头，不匹配 `}` 前缀，不会被误过滤。
- 返回 `filtered_technical`/`offset`/`limit` 字段供前端透传。
- Rule 搜索继续按所属 Cube 定位（非独立 Rule 目录，保留既有语义）。

新增单测 `test_visible_objects_filters_brace_technical_but_keeps_legal_names`（`tests/test_engineering_workbench.py`）。

### 2. 审计 showNode/showEdge 与 TM1Inspector 摘要复用

- TI 详情复用 writes 分析（`/api/workbench/writes`），`loadWrites` 按钮在 process 详情打开时自动触发，概览显示紧凑切面（写入方式/目标 Cube/固定切面/运行时坐标），详细切面与源码值表达式进「源码与证据」层。
- Rule 详情复用语义 IR（`/api/workbench/rules`），显示相关 Rule 数、目标区域、已确认引用 Cube、条件分支；Feeder 明确不表示数值贡献。
- 请求失败：`AbortError` 直接 return；其它错误调 `TM1Inspector.writes/rules` 的 error 分支显示「未取得…不能据此认定没有…」，不用空列表伪装成功。

### 3. 错误/取消/元数据缺失的明确反馈

- `canvas-experience.js` 的 `writes()` 区分三种状态：接口错误、`total==0`（未解析到写入）、`total>0` 但无业务 Cube（系统对象写入），各自显式说明。
- 消费 `data.limitations`，逐条展示限制。
- 概览 ViewModel 的事实 → evidence 映射表已写入 `FRONTEND_BACKEND_CONTRACT.md`（TI 写入概览、Rule 概览逐项对应后端字段与边界）。

### 4. Workspace v3 草稿保存恢复

- 设计草稿（DESIGN_DRAFT）空维度仍标注「未部署 / 未验证」。
- Snapshot 不匹配时 `files.load` 抛「模型已变化」，恢复被拒绝（HTTP 409 实测通过）。
- 刷新后维度/Cube/Schema/关系/映射/Blueprint/人工模块均恢复。

### 5. 手工位置锁定 + 增量新节点布局

- 保留既有手工坐标（positions 持久化）；新节点由 `addCubeDraft` 在中心附近避让放置。
- 布局引擎纯函数 `TM1CanvasLayout.compute`：Tarjan SCC 收缩 + 最长路径分层 + 重心排序；上游放上游、下游放下游，循环（SCC）不推断顺序。
- 自环（`loop-sweep`）、平行边（`unbundled-bezier`）、大扇出、120 节点均覆盖。

### 6. 设计关系全链路

- 拖线（Esc 取消、目标高亮、松手开映射）、精确名称映射、`/design/generate`、`design_fingerprint` 的 STALE 判定、`cube-spec` 生成说明。
- 生成面板明确标注 `DESIGN_DRAFT`、`未在 TM1 Server 部署或执行`、清空范围、数据源变量契约、已知限制。
- 生成成功 ≠ 运行验证；不伪造 `VERIFIED_ASSET`。

### 7. 键盘/焦点/竞态/窄屏

- 画布容器 `tabindex=0` + keydown 方向键最近邻移动 + Enter 选择，`cn-kb-focus` 虚线边框。
- 创建菜单展开后聚焦首个 `cx-menuitem`，方向键/Home/End 移动焦点，Esc 回焦。
- 关闭 Inspector 保留图与选择（`detailGeneration` 令牌防异步竞态）。
- 窄屏（1366×768）无纵向长滚动、无节点碰撞、点搜索结果后资源栏自动收起让位画布。
- `prefers-reduced-motion` 保留。

### 8. 验收脚本迁移

`acceptance_canvas.py`/`design.py`/`assets.py`/`pointer.py`/`workbench.py`/`excellence.py` 六个脚本从旧顶层「探索/设计」切换迁移到「＋创建」入口：

- 删 `enter_design`（旧 `#ew-mode-design`），改为经「＋创建 → 维度草稿」进入设计模式并展开侧栏。
- 关闭详情选择器统一为 `button[aria-label='关闭详情']`。
- 搜索前先展开资源栏（默认 `rail-collapsed`）。
- 跨 section 操作前恢复目标 section 可见（`openCreateSection` 只显示单 section）。
- 未删任何断言，仅迁移定位方式。

### 9. 测试与验收

- **pytest**：1099 passed（基线 1098 + 新增 1）。
- **浏览器验收**（独立合成服务，端口 8811，`TM1_INSIGHT_HOME` 隔离 + demo 只读）：

| 脚本 | 断言数 | 结果 |
|---|---|---|
| acceptance_canvas.py | 30 | ✅ |
| acceptance_design.py | 34 | ✅ |
| acceptance_assets.py | 17 | ✅ |
| acceptance_pointer.py | 12 | ✅ |
| acceptance_workbench.py | 40 | ✅ |
| acceptance_excellence.py | 20 | ✅ |

准确通过/失败数由脚本 `failures` 计数累加，退出码 0（全绿）/1（有失败），无 skipped 项（浏览器验收为真实点击，不存在 skip）。

## 修改文件

| 文件 | 变化 |
|---|---|
| src/tm1_insight/api/workbench.py | `visible_objects()` 纯函数 + objects 路由 `include_technical/limit/offset` |
| src/tm1_insight/api/static/architecture-workbench.js | 系统对象过滤、showNode/showEdge 错误处理、writes 自动分析、创建菜单动作 |
| src/tm1_insight/api/static/canvas-experience.js | `writes()` 区分错误/空/限制三态 |
| src/tm1_insight/api/static/canvas-graph.js | 键盘导航（方向键/Enter/cn-kb-focus） |
| src/tm1_insight/api/static/canvas-shell.js | 创建菜单焦点管理 |
| src/tm1_insight/api/static/canvas.css | `.cn-canvas:focus-visible` 等 |
| tests/test_engineering_workbench.py | 新增 visible_objects 过滤测试 |
| docs/architecture-canvas/FRONTEND_BACKEND_CONTRACT.md | objects 接口契约 + evidence 映射表 |
| scripts/acceptance_{canvas,design,assets,pointer,workbench,excellence}.py | 迁移「＋创建」交互 |

## 数据安全

未连接 TM1 / 内网；未执行 TI / MDX；未读 Cube Cell；未打开或覆盖正式 DuckDB / WAL。自动化服务用独立用户目录（`TM1_INSIGHT_HOME`），模型连接限制为该私有目录且 read_only。测试只写隔离合成库与测试工作区文件。

## 剩余风险与下一步

- 企业真实模型验收未做，不能宣称所有大模型交互已验证。
- 源切面、动态坐标、Data 行变量缺证据时仍未确认，未扩大后端语义。
- Rule 搜索按所属 Cube 定位，非独立 Rule 资产目录（保留既有语义，未新建）。
- 新增节点增量布局保留手工坐标，不承诺任意手工布局下每条边都朝右。
- 本轮未提交/推送；下一步由用户决定是否 `/commit`。
