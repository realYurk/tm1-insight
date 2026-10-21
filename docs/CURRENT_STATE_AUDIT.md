# CURRENT_STATE_AUDIT — Architecture Workbench 1.0 接管审计

> 审计时间：2026-10-21 · 分支 `codex/product-evolution-01` · 基线 `8ef6d67`
> 结论基于真实源码、真实快照与真实浏览器行为，不引用任何未落地的开发日志。

## 1. 仓库现场

| 项 | 实际值 |
|---|---|
| 当前分支 | `codex/product-evolution-01` |
| HEAD | `8ef6d67`（= `master` = `origin/master`） |
| 未提交修改 | 9 个已跟踪文件 |
| 未跟踪新文件 | 10 个（工作台主体） |
| 冲突 | 无 |
| `stash` | 空 |

接管前已将现场**无损备份**到仓库外：

```
D:\06_Backup\Work\work文件\tm1-atlas\tm1-suite\_handoff_backup_20261021-192717
├── tracked-changes.patch   # 9 个修改文件的完整补丁
├── untracked-list.txt
├── files/                  # 10 个未跟踪文件的原始副本
└── HEAD.txt
```

未执行 `reset --hard`、`clean -fd`、`restore`、`rebase` 或任何可能丢弃现场的操作。

## 2. GPT-6 实际交付的内容

工作台并非 Mock，也不是空壳。真实存在且可用：

| 模块 | 文件 | 真实能力 |
|---|---|---|
| 图查询内核 | `src/tm1_insight/workbench.py` | 有界投影、预算、前缀分页、稳定 id、快照隔离、工作区模型与原子保存 |
| API | `src/tm1_insight/api/workbench.py` | graph / objects / detail / writes / rules / workspaces CRUD |
| Rule·Feeder 分类 | `src/tm1_insight/workbench_rules.py` | 复用既有 `unified_relations` 语义 IR，不再使用文件级索引 |
| 前端 | `static/architecture-workbench.js`、`.css` | 图、关系表、右侧详情、多选、框选、人工模块、草稿、保存恢复、模板跳转 |
| 持久化客户端 | `static/workspace-persistence.js` | 请求封装与导出 |
| 模板桥 | `static/workspace-codegen.js` | 带入来源/目标 + 返回原工作区 |
| 模板 | `templates/architecture_workbench.html` | 工作台 DOM |
| 测试 | `tests/test_engineering_workbench.py` | 26 项离线契约测试 |

## 3. 发现的真实缺陷（本轮已修）

| # | 缺陷 | 影响 | 处理 |
|---|---|---|---|
| 1 | `workspaces/` 未纳入 `.gitignore` | 工作区含企业对象名、备注、MDX，位于仓库根目录，`git add .` 会误入库 | 加入 `.gitignore`，`git check-ignore` 验证 |
| 2 | `limits.truncated` 恒为真 | 把「局部视图边界」混同「预算截断」，截断提示失去意义 | 拆分：`truncated` 仅表预算丢弃，`boundary` 单独表达视图边界；Rule 预算不足改由 `rule_scope_complete` 表达 |
| 3 | 固定目标成员/运行时坐标埋在折叠 `<details>` 内 | 用户看不到「固定切面 vs 动态坐标」这一核心结论 | 写入面板新增默认可见的切面聚合块 |
| 4 | 每条写入附约 5–10KB JSON，38 条即约 250KB DOM | 详情面板卡顿 | 证据改为**首次展开才渲染**，并截断至 6KB |
| 5 | 点击图上的边只改颜色，不定位表格 | 「图 → 表」联动只做了一半 | `scrollIntoView` 滚动到对应记录 |
| 6 | `mermaid-viewer.js` 版本引用分散（v1/v2/v3） | 浏览器可能加载旧副本，框选等功能失效 | 统一为 `v=3` |
| 7 | 每页 `/favicon.ico` 404 控制台报错 | 噪声掩盖真实错误 | `base.html` 内联空 icon |
| 8 | 验收脚本硬编码 `127.0.0.1:8000` | 无法在其它端口复跑 | 统一读 `TM1_BASE` |

## 4. 核实为「属实」的 GPT 报告

- 图查询、关系表、右侧源码详情已连通，且同页切换不清空画布。
- 人工编组、折叠、保存、刷新恢复真实可用（浏览器实测）。
- 备注与 MDX 文本可保存，且明确标注为人工输入、不执行。
- 快照身份隔离真实生效（异快照返回 409，不按名称重绑）。
- 保存中断保护真实：临时文件 + `fsync` + `os.replace` + `sha256` 版本校验 + 单份 `.bak`。
- ACT TI 的源码与写入切面可在 UI 中核对（详见 `VALIDATION_REPORT.md`）。

## 5. 核实为「不准确」或「未完成」的部分

| GPT 报告 | 实际 |
|---|---|
| 「专项测试 22 passed」 | 实为 **26**（参数化展开后）；本轮新增 1 项，共 **27** |
| 「正在修复 Rule 与 Feeder 混淆」 | **已完成**，且经真实模型验证 |
| 「正在验证 ACT TI 源码与写入切面」 | **已完成**，证据充分 |
| 「正在验证模板往返」 | 已实现，但只在选中两个 Cube 时出现入口；本轮补验收 |
| 「正在准备交接文档」 | **未落地**，5 份文档均不存在，本轮补齐 |
| 「896 passed」 | 真实基线 896；本轮为 **923**（896 + 27） |

## 6. 本轮修改方案（最小增量）

只做「让已有功能正确、可读、可信」的修复，不新建第二套引擎、不改产品方向：

- 数据安全 1 处（`.gitignore`）
- 语义 1 处（`truncated` / `boundary` / `rule_scope_complete` 三者分离）
- 交互 2 处（切面默认可见、图→表滚动定位）
- 性能 1 处（证据懒渲染）
- 一致性 4 处（Mermaid 版本、favicon、`TM1_BASE`、`base.html` 导航）
- 验收 2 个新脚本（`acceptance_workbench.py`、`perf_workbench.py`）

未改动的核心：图查询内核的数据结构、工作区 Schema、Rule 语义解析、源码组件、代码模板引擎、分摊引擎。
