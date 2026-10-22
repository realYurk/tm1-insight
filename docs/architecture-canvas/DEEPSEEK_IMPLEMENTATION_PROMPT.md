# 可直接交给 DeepSeek 的开发任务

你是 TM1 Insight 后续实施工程师。当前真实分支是 `codex/canvas-excellence-04`，Codex 本轮基线为 `0f79bcf`，其后 UI 改动尚未提交。先运行 git status、git branch --show-current、git log -5 --oneline，完整阅读 PRODUCT_CONSTITUTION.md、AGENTS.md 和 docs/architecture-canvas 下本轮五份文档。以仓库当前代码为准，禁止编造不存在的 API 或文件。保留全部未提交成果；不切旧 master、不 reset/clean/rebase、不自动提交或推送。

## 已确定的交互体系，不得重做

画布主导；左右辅助栏按需出现；空搜索为引导与最近访问；单一“＋ 创建”；Inspector 分“概览 / 源码与证据”；默认 LR 分层、可切 TB；关系类型保留，不将共同读写冒充值流。沿用当前 Cube 图标、克制的颜色和 Cytoscape 离线画布，不能退回中心环绕、大屏或表单堆砌。

Codex 修改的准确位置：

- `src/tm1_insight/api/templates/architecture_workbench.html`：创建菜单、空态、搜索、辅助区域披露。
- `src/tm1_insight/api/templates/architecture.html`：资源引入顺序与版本。
- `src/tm1_insight/api/static/canvas-experience.js`：新 Inspector 展示适配器。
- `src/tm1_insight/api/static/architecture-workbench.js`：空搜索/最近访问、详情摘要、创建动作、局部展开坐标保留。
- `src/tm1_insight/api/static/canvas-layout.js`：默认有向分层、SCC 成员排布、TB。
- `src/tm1_insight/api/static/canvas-graph.js`：核心点击反馈关闭、TI 图标、方向及减少动画。
- `src/tm1_insight/api/static/canvas-shell.js`、`canvas.css`：辅助面板、创建菜单、紧凑布局。
- `tests/test_canvas_ux.py`：纯 JS 布局合成测试。

## 已真实存在的能力，禁止重新实现

Graph API、Rule Semantic IR、Expression IR、统一关系、TI 写入分析、工作区 v3 的持久化与冲突保护、设计草稿模型、本地校验与模板生成都已经存在。先检查 `workbench.py`、`api/workbench.py`、`design.py`、`workbench_rules.py`、`unified_relations.py` 和现有 codegen 路由再编码。

新 UI 已接现有接口；不是一套只有假数据的原型。此次浏览器验收使用隔离合成模型，不等同于真实企业模型验收。CSV Schema 是用户声明，未读取文件；草稿与生成代码都未部署。SQL 创建和自动源切面还原未实现，不得加假按钮或编造来源。

## 请按以下顺序补齐并验证

1. 保持现有响应兼容，为对象目录补充真正的服务端系统对象显示过滤，过滤后再分页。依据明确元数据/命名规则，保留开关；不得硬编码排除 Sys Parameter 或 #######。Rule 搜索按所属 Cube 兼容，若增加专门目录，必须基于已有 Rule IR，保留旧参数。
2. 审计 `showNode/showEdge` 与 `TM1Inspector`。TI 摘要应复用现有 writes 分析，Rule 摘要应复用原 IR。考虑缓存、请求取消、源变更检测和批量局部查询；不要重新解析整个企业模型来填摘要。维持源切面缺失、动态坐标、Data 行绑定未知和 Feeder 边界。
3. 让 API 错误、取消、元数据缺失在简洁的概览中有明确反馈。不得用空列表伪装为成功分析。若提供 summary ViewModel，版本化并保留当前端点；文档列出每项事实的 evidence 引用。
4. 核对当前 Workspace v3 已支持的草稿 Cube、维度、Schema、关系、groups、positions、layout 和 revision；在原实现上修复保存恢复，不能创建第二套存储。草稿为空维度时仍必须明确未完成，校验与生成不得当成已部署模型。Snapshot 不匹配必须拒绝自动重绑。
5. 继续完善手工位置锁定与增量新节点布局：原节点不移动，新上游应放在上游、新下游放在下游，循环不推断执行顺序。显式自动布局才覆盖全部位置。验证 LR/TB 的保存恢复、折叠、过滤、多源汇聚、大扇出与自环。
6. 检查既有设计关系拖线、映射表单、`design/validate|generate|stale|cube-spec`、现有代码生成页和模板调用。复用既有模板与成果状态，生成成功不等于运行验证。若返回成果标识缺失，记录缺口，禁止伪造 VERIFIED_ASSET。
7. 补足键盘选择、创建菜单焦点管理、关闭面板与选择保持、重复点击和异步竞态、窄屏布局。保留 `prefers-reduced-motion`。不得擅自改变已经确定的视觉体系。
8. 迁移 `scripts/acceptance_canvas.py` 和其他浏览器验收中的旧顶层模式按钮点击，改用可见“＋ 创建”入口；不能直接删断言。保留拖线、生成、保存恢复和关系语义的有效验收。
9. 执行专项和完整 pytest，独立合成服务上真实点击测试，再给出准确的通过/失败/跳过数。不同浏览器或测试方法必须分开记录，不能引用历史截图作为新版本通过证据。

## 数据契约与安全

完整契约见 `FRONTEND_BACKEND_CONTRACT.md`。沿用 stable_id(snapshot,type,name)、GraphQuery、relation_kind/status/evidence/unresolved_reasons；不同类型边不能按端点盲并。`TI_CANDIDATE` 未证明值流；Rule 声明式；Feeder 非数值贡献；MODEL_FACT、STATIC_ANALYSIS、USER_INTERPRETATION、DESIGN_DRAFT、DESIGN_RELATION 不混用。

禁止连接 TM1 Server、探测企业网络、读取 Cube Cell、执行 MDX 取数、执行 TI、修改正式 DuckDB/WAL/Snapshot、上传源码或资料、集成 AI。只用仓库和合成数据。自动化服务使用独立用户目录，测试结束只清理本次进程，不影响用户既有服务。保持 Portable 软件与客户数据分离。

## 最终验收

从合成 Cube 搜索 → 查看 TI 读写/写入方式/固定与动态切面 → 关闭详情保留图与选择 → 查看 Rule 目标与来源 → 切换证据/源码 → 多选编组 → 保存恢复 → 创建 Cube 草稿 → 声明 CSV Schema 并拖线 → 复用原模板生成草案/校验 → 返回原工作区。

再覆盖自环、SCC、大扇出、120 节点预算、未知源值、坏文件、版本不兼容、409 冲突、减少动画、窄窗口。不能把未接入的占位 UI 宣布为完成。

可自主连续完成编码、测试、修复，无需每一步确认；产品语义、安全边界或删除现有功能的决定不可擅自改变。最后输出：实际文件差异、功能接入状态、合成浏览器证据、全量测试、性能、数据安全、剩余风险及下一步；不自动推送或发布。
