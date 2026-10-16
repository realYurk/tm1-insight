# Workbench 1.1 进度 — 真实交付验证与统一对象浏览器

> 任务：验证 Workbench 1.0 真实运行情况；建设统一对象浏览器（Cube/Dimension 双栏）；
> 完整跨对象上下文记忆；真实浏览器验收。
> 纪律：不引入 AI/LLM/新框架；不动 TI Parser / Rule 语义 / Lineage Engine；不 Push（除非用户授权）。

## 阶段 A：环境与版本验证 ✅

### 「用户看不到 Workbench 1.0」根因（有证据）
1. **Portable EXE 停留在 10 月 12 日构建**（release/portable-20261012-222757），不含
   Workbench 1.0（10 月 15-16 日提交）的任何改动。用户双击 EXE 看到的是旧界面。
2. **运行中的旧服务进程不自动加载新代码**：发现两个 `tm1_insight.cli web` 进程，
   其中一个（anaconda python 启动）占用 8000 端口、无 --reload，返回的页面只有
   Workbench 1.0 改动、无 1.1 内容。源码更新后必须重启服务 / 重新打包。
3. **无任何可见版本信息**：用户无法区分开发版 / Portable 版。

### 版本信息可见化（本轮新增）
- 新增 `src/tm1_insight/buildinfo.py`：version / git 短 SHA（读 .git/HEAD）/ 构建时间
  （打包模式读 BUILD_MANIFEST.json）/ 运行模式（sys.frozen）。源码模式 build_time=None，
  明确「未打包」，不伪造。
- `app.py` 注入模板全局 `build_info`；`base.html` 侧边栏底部显示
  `v0.3.0 · <sha> [开发版/Portable]`；`settings.html` 新增「关于 / 版本信息」卡片。
- 不暴露密码 / Token / 完整私有路径（测试 test_workbench_version_info.py 覆盖）。

### Portable 测试构建 ✅ 完成
- `release/portable-20261016-191616/dist/TM1 Insight/`（TM1 Insight.exe + _internal）。
- BUILD_MANIFEST.json：built_at=20261016-191616，contains_customer_data=False。
- 新资源已入包：workbench-context.js、_cube_detail.html。
- `TM1 Insight.exe --self-check` → {"status":"ok","version":"0.3.0","routes":67}。

## 阶段 B：Cube 双栏对象浏览器 ✅

- Cube 详情主体抽取为 `templates/_cube_detail.html` 片段，双栏页与独立详情页共用；
  `/explorer/cube/{name}` 深链接完全兼容。
- `/cubes` 升级为双栏：新增 `name` 参数，选中时同时渲染
  get_cube + cube_lineage 详情（复用 `.dimension-workspace` 布局，
  左列表 260-300px + 右详情，小屏自动单栏）。
- 左列表：搜索、选中高亮（aria-current）、分页（100/页）、空态提示。
- 搜索提交后自动选中第一个结果，右侧直接显示详情。
- 未知 name → 404 错误页（不静默）。
- Dimension 页面原本已是双栏（dimensions.html），体验一致。

## 阶段 C：完整对象上下文记忆 ✅

- 修复 workbench-context.js 缺陷：preference/setPreference 之前误用 sessionStorage，
  现已改为 **localStorage**（长期偏好跨会话保留）；两类存储均版本化（VERSION='wb2'，
  旧 wb1 结构自动失效）。
- rememberList 现在包含选中对象名（name）。
- 新增 rememberJump / recallJump：Cube 详情页记录「来源 Cube」，
  Dimension / TI 页顶部自动显示「← 返回来源 Cube：X」链接（保留搜索词与页码）。
- 浏览器后退天然可用（普通链接导航，URL 承载全部状态）。

## 阶段 D：详情页降噪与统一 ✅

- Cube 阅读顺序符合要求：名称→维度结构→数据形成→写入 TI→使用与去向→前端→Rule。
- 写入 TI 紧凑列表 + 搜索 + 分页（>20 分页）；固定常量/参数/变量三样式高亮。
- Dimension 保持 TreeGrid + 属性列偏好 + 子集面板；技术原始记录默认折叠。

## 阶段 E：真实浏览器验证 ✅（agent-browser / Chromium 实测）

截图（images/）：
- workbench11-cube-explorer.png：Cube 双栏（列表 3338 个、选中高亮、右侧详情、版本信息）
- workbench11-dimension-back-link.png：Dimension 页 + 「← 返回来源 Cube」入口
- workbench11-ti-back-link.png：TI 页 + 「← 返回来源 Cube」入口
- workbench11-cube-search.png：搜索 Allocation 自动选中第一个结果
- workbench11-cube-dark.png：深色主题下双栏 + 固定值 ACT 高亮清晰

交互闭环（真实浏览器操作记录）：
1. /cubes → 选中 Actual Amount For Plant Base And Policy ✓
2. 点击维度 Company → /dimensions?name=Company ✓（显示返回来源 Cube）
3. 点击「返回来源 Cube」→ /cubes?name=Actual Amount...，右侧直接恢复原 Cube ✓
4. Cube → TI → 返回 Cube ✓
5. 搜索 Allocation → 自动选中 Allocation Calculation ✓
6. 深色模式切换 → 布局与高亮正常 ✓

## 测试

- 新增：test_workbench_version_info.py(4)、test_workbench_cube_explorer.py(4)、
  test_workbench_context_cube.py 扩展(+2)
- 全量：**572 passed, 0 failed**（基线 562 → 572）
- python -m py_compile / node --check 全部通过

## 启动方式

- 开发版（推荐验证）：`start.bat`，或
  `.venv\Scripts\python.exe -m tm1_insight.cli web`（先关闭旧的 8000 端口进程）。
- Portable：`release\portable-20261016-191616\dist\TM1 Insight\TM1 Insight.exe`（双击）。
- 核对版本：侧边栏底部应显示 `v0.3.0 · <当前短SHA> 开发版`（或 Portable），
  或访问 `/settings` 的「关于 / 版本信息」。

## 遗留

- 用户机器上的旧 8000 端口进程需手动关闭后重启，才能看到新版（本文档提供步骤）。
- 大维度 search 的 total 真实匹配数仍需全量 count（~1.3s / 68 万元素），
  可后续用 dimension_index 的 SQLite 索引加速。
- 键盘上下选择列表未实现（低优先级，可后续迭代）。
