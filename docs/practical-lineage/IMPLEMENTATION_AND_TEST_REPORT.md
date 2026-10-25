# Phase 0 / Phase 1 实施与验收

日期：2026-10-24。当前分支 `codex/canvas-excellence-04`，核对 HEAD `24ef873c24c75a6042f068330914526dadca69b6`。没有提交、推送、合并或重置。保留本轮开始前全部未提交成果。

## 修改清单
- `api/static/architecture-workbench.js`：可恢复只读开关，禁用 changed/remember 的持久编辑路径、保存/导入/创建入口、草稿连线、代码模板工作区保存跳转；历史工作区可读，设计资产不混入模型图。
- `api/templates/architecture_workbench.html`、`api/static/canvas.css`：只读标识与设计入口隐藏，历史笔记只读，去掉创建提示；`api/templates/architecture.html` 更新静态资源版本。
- `api/app.py`、`api/templates/graph.html`：Cube 血缘路由接入，原 TI 路由兼容。
- `api/templates/cube_lineage.html`、`api/static/cube-lineage.js`、`api/static/cube-lineage.css`：关系表、逐 TI/写入切面、Rule 详情、辅助 Cube 简图与当前范围导出。
- `api/workbench.py`：仅向 writes 增加现有 Calculation 读取节点、控制上下文等字段，不修改分析语义。
- `tests/test_cube_lineage_ui.py`：10 个合成测试。
- 本目录五份文档。
路径均相对 `src/tm1_insight/`（tests/docs 除外）。其他已有 canvas 改动与 `scripts/acceptance_excellence.py` 修改保留，并非本轮全部重写。

## 实际功能与证据
合成 Unbound：`discard=CellGetN('Cube_A',pYear,'Member1');CellIncrementN(vValue,'Cube_B',pYear,'Member1','Member2');`。
在 data:1:44，源切面未确认；Year=pYear 为动态，Region=Member1 与 Measure=Member2 经合成维度目录确认固定；操作为累加。不能因先前读取 Cube_A 而认定 vValue 来源已证明。
合成 Multiple：第一个 `a*2` 写入有 Cube_A 静态读取节点；第二个 `vUnknown` 写入无该来源证明，两个目标切面分开。Journal 共同读取不被当作本值表达式来源。
RuleOutput：`['Member1']=N:DB('Cube_B',!Year,'Member1','Member1');`；引用 Cube_B 已确认，目标裸成员的维度归属仍待确认。

## 自动测试
基线：`.venv\Scripts\python.exe scripts/run_offline_tests.py -q` → **1099 passed, 1 warning, 129.19s**。
专项：同 runner 加 `tests/test_cube_lineage_ui.py tests/test_engineering_workbench.py -q` → **38 passed, 1 warning, 3.70s**。
完整回归：同 runner `-q` → **1109 passed, 1 warning, 146.37s**。
警告为现有 Starlette TestClient/httpx 弃用提醒，无失败/跳过。交付前专项重跑：38 passed, 1 warning, 4.07s。Node 语法检查与 git diff --check 通过。基线/回归输出保存在临时测试目录（未将企业数据放入仓库）。
测试覆盖：单源、多 TI、多源、两个独立写入、Rule 与 TI 并存、自环、上下游方向、动态对象、源未知目标已知、无证据负例、旧坐标缺绑定、API 增量兼容与旧路由。

## 浏览器实际交互（仅独立合成服务 8806）
- Cube_B 默认显示 4 条关系 / 4 个 Cube；Cube_A→Cube_B 聚合 Load/Unbound/Multiple，RuleOutput 为独立 Rule，下游含自环。
- 展开 Unbound 显示未知源和正确固定/动态目标；Multiple 两个写入不串接源依赖。
- Rule 展示 DB 参数与目标裸成员的未确认维度；辅助图离线渲染并保留自环。
- 上游显示 3 关系，下游显示 2 关系；Unrelated 显示 0 关系，无虚构连接。
- 架构连续搜索并打开 Cube_A、Cube_B、Journal、RuleOutput、Unrelated、Sys Parameter、#######、Load、Unbound、Multiple；各次状态都是“只读浏览”。随后缩放、自动布局、切方向、拖动节点、平移，退出至血缘页无 beforeunload 对话框。
- 创建/保存按钮不可见。合成历史工作区可以恢复，草稿/备注文件哈希未变，仅有原 1 个工作区文件。测试准备阶段用现有 Workspace 写入器创建该合成历史文件，不属于浏览写入。
- 合成 DuckDB 浏览前后 SHA256 相同。HTTP 非 GET 记录仅 `POST /api/workbench/graph`，无保存/设计/导入请求。
- 点击导出并解析实际下载的 Markdown JSON 附录：schema 正确、4 条关系、1 个主动核对 TI，未知源未被改写；文件 10664 字节。

截图及验收产物目录：
`<local-acceptance>/cube-lineage-readonly/`
包含 `cube-lineage-default.png`、`source-unknown-target-known.png`、`cube-relations-and-diagram.png`、`readonly-architecture.png`、`Cube-Lineage.md`、`safety-result.json`、`performance.json`。

## 性能、安全与兼容
合成服务局部请求一次实测：graph 50.07ms、4 节点/4 边、JSON 4891 字节；Unbound writes 30.49ms、JSON 2278 字节。仅为本机热缓存合成数据测量，不外推大型模型或浏览器帧率。沿用原索引缓存/图预算/Rule 预算；每个 TI 仅在点击后读取一次分析，不为首屏读取所有 TI 正文。
只操作源码、合成 DuckDB 和私有合成工作区；未连接 TM1、未读取单元格/执行 TI/MDX，未修改正式 Snapshot/DuckDB/WAL，未上传企业数据。原 API/Workspace v3/代码生成和旧 TI 路由保留。

## 未完成与 Phase 2 建议
- 没有真实 BP 数据验收，本轮遵照合成隔离约束；不得将合成效果当作真实 ACT/Step2 结果。
- VIEW/Subset 完整源范围未新增解析；未绑定行变量继续未知。
- 无来源的写入不生成 Cube→Cube 假边，通过 Cube 详情查看全部 writer。
- 只显示直接上下游，超预算不宣称完整。原候选投影的全索引/50000 候选上限仍存在，本轮不重写图算法。
- 规则字面量坐标可展示，维度归属不补猜；Feeder 未加入默认数值主表。
- 完整三层报告、TI 调用表与参数/条件增强留给 Phase 2；不开展新设计器、Java/SQL/AI 或导航重构。

## 续作记录
后续用户要求“继续”，Phase 2 交付见 [TI 调用与重构闭环](PHASE_2_IMPLEMENTATION_REPORT.md)。本文件保留 Phase 0/1 的历史测试与范围，不将后续结果冒充同一轮验收。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
