# Chore 工作台与安全采集进度（2026-10-13）

## 1. 产品结果与验收范围

支柱：Reverse Engineer / Prove / Govern。交付用户反馈 17 的独立 Chore 双栏入口，以及 10 的采集/扫描真实进度。继续遵守根目录 Product Constitution 和 AGENTS。

最小闭环：搜索调度 → 选择一个 Chore → 核对记录次序/缺口 → 打开 TI 源码；启动采集/扫描 → 看到实际阶段和计数 → 离页返回 → 完成或取消 → 结果/数据源一致。

不包含：运行 TI、验证业务数值、公式 IR 新引擎、完整快照版本管理、全站视觉重做或生成新的发行 exe。

## 2. 源码问题与最小设计

- 原 Chore 被放在长 TI 列表底部，详情占满页面；步骤 JSON 未归一化或排序，并把存储列表直接称为执行次序。
- 原 Chore 采集器用位置替代缺失序号，且 `or` 会丢掉显式 0。现在保留 0，缺失序号保留 None；关系入库也不默认补 0。历史库没有重写。
- 原 Web 采集直接 `Loader(...).load(drop=True)` 重建当前数据库；进度只有终端日志；启动线程之前未预留任务状态，存在重复启动窗口。
- 原扫描已有文件回调，但没有枚举/保存阶段，两个页面维护不同轮询，无法一致恢复/停止/取消。

继续使用现有 FastAPI/Jinja、DuckDB、Exporter、Loader 和扫描侧库。只为 Web 采集新增独立目录构建与成功后原子选择，不重写解析器或数据库模式。

## 3. 代码与接口

- `store/queries.py`：Chore 名称字面量分页；规范化步骤；只排序有效、唯一的显式序号；保留原 JSON 位置与原始序号；批量检查 TI 是否存在；数量冲突、JSON 损坏与缺失名称可见。
- `api/app.py`、`templates/chore_view.html`、`templates/base.html`、`templates/processes.html`：新增 `/chores` 独立导航、左侧 50 项分页与右侧 100 条步骤分页；旧 `/explorer/chore/{name}` 兼容。
- `tm1/client.py`、`ingest/loader.py`：不虚构缺失调度序号；保留合法 0。
- `ingest/progress.py`：明确 16 个采集阶段与 4 个扫描阶段；只有实际对象计数可计算比例，阶段位置不是总耗时百分比。
- `ingest/exporter.py`、`ingest/loader.py`：可选进度回调和 strict 模式；Web 启用 strict、全量采集到新目录；失败对象、维度文件读取失败或解析异常阻止选择新模型。CLI 默认保持原方式。
- `api/app.py`、`config.py`：启动预留；构建 `collections/model-*`；对账 Cube/TI/Dimension/Chore 数量并确认 Cube 非空；原子比较原选择后切换；中途换库则不覆盖用户选择。失败信息不回显底层异常内容。
- `ingest/audit.py`：枚举、文件扫描、事务保存均报告阶段；继续使用原有事务替换和独立侧库。
- `static/job-progress.js`、`templates/job_progress.html`、`templates/settings.html`、`templates/audit.html`：统一等待、计数、恢复、错误、完成入口和取消；停止后不继续播放等待条；完成不自动刷新抹掉进度；换库时隐藏旧扫描进度并刷新目录与来源标签。
- 新增 `/api/ingest/cancel`、`/api/audit/cancel`；现有状态接口增加 progress/cancel 字段，保留 running/done/error/stats；状态响应无缓存。
- `workbench.css`：紧凑 Chore 列表、响应式双栏和进度面板；复用现有明暗主题。
- `.gitignore`、发布保护及其测试排除私有 `collections/`。不提交模型、日志、凭据、私有教材或本机真实数据测量记录。

## 4. 证据示例与 UNKNOWN

合成 Chore 原 JSON 存储 `[Calc_Finance(step=2), Load_Sales(step=1)]`。页面按 1、2 展示，但来源仍分别是 `chores.processes[1]` 和 `[0]`，没有把排序后位置伪装成原始索引。

如果两个步骤都记录 step=1，页面保留存储位置，显示 PARTIAL，不产生确定执行次序。缺失 TI 仅表示当前本地库未找到，不能据此宣称服务器对象被删除。关系表回退明确标为 `chore_runs_process.step_order`。

合成采集的第 3/16 阶段有 2 个 Cube，真实回调依次为 0/2、1/2、2/2（本阶段 0%、50%、100%）；后续阶段仍需继续，不把它称为整项任务 100%。扫描的文件阶段同样有真实 current/total。

合成 TI 包含 `ExecuteProcess(pDynamicChild)`；本轮不尝试证明其被调对象，不从 Chore 次序推断 Cube 值流，不宣称迁移等价。

## 5. 测试和浏览器验证

统一使用隔离临时 `TM1_INSIGHT_HOME`：

```powershell
$tm1TestHome = Join-Path ([System.IO.Path]::GetTempPath()) ('tm1-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tm1TestHome | Out-Null
$env:TM1_INSIGHT_HOME = $tm1TestHome
.venv/Scripts/python.exe -m pytest -q
node --check src/tm1_insight/api/static/job-progress.js
node --check src/tm1_insight/api/static/process-search.js
git diff --check
```

最终复验：387 passed，1 warning。保留原 Starlette/httpx 弃用警告，没有移除或弱化既有测试。两份 JavaScript 的语法检查及 Git 差异检查通过。

测试文件：`tests/test_chore_workspace.py`、`tests/test_collection_progress.py`、`tests/test_publication_guard.py`，并运行完整回归。合成传输驱动真实 Exporter/Loader 和 DuckDB/Parquet，覆盖成功、连接失败、对象失败、解析失败、数量不符、中途换库、重复启动、线程启动失败、取消、原库字节不变和扫描侧库保留。

资源测试使用 1128 项合成调度/步骤验证分页；取消解析时只提交第一批 16 个任务，不排队整模型。

浏览器：双栏、步骤来源索引、缺失/重复序号、菜单分页、窄屏/深色主题；扫描开始立即反馈，离页返回恢复文件计数；取消后按钮恢复；完成第 16/16 阶段后两处 Local 标签同步；来源变化隐藏旧扫描状态并更新目录。前端资产页单独验证保存目录、无效目录失败恢复、真实重新扫描和查看 40 个合成资产/映射；修复适配时遗漏的目录读取函数，无新增脚本异常。合成截图留本机附件，不进入公开仓库。

## 6. 安全、性能与回退

真实库只读验证主文件和 WAL 的大小、mtime、流式 SHA-256 一致。测量记录仅保存在本机附件；未连接真实 TM1，没有执行业务 TI 或修改原始数据。

Chore 列表最多 50 项、步骤页面最多 100 条；当前所选 Chore 的 JSON 仍整体读取，未建立新的数据库索引。TI 解析池每次最多提交 workers×16 个对象，取消后只等待当前批次和正在执行的操作。

Web 新目录构建成功后才修改数据源指针；写入/校验失败及取消保留原库。对象数量校验不是业务数值或完整语义等价证明。CLI 的既有原地入库行为没有在本轮改造成新目录流程。

代码可通过 Git 回退；已构建模型目录保留在用户目录，可由设置重新选择旧库。本轮不自动删除历史库或未完成目录，也不提供历史清理 UI。

## 7. 限制

- 任务状态仍在单个服务进程内；跨页面可恢复，服务重启后不会恢复任务状态。不是跨进程调度系统。
- 取消是检查点取消，不能立刻中断正在执行的网络请求、单个大文件读取或当前解析批次。
- 新建库占用额外磁盘空间；完整版本浏览、保留策略、失败目录管理和升级后的旧 exe 验证仍待实现。
- 采集器已有 Rule/Feeder、权限、动态引用和 TM1py 版本边界。校验成功仅表示支持范围内的采集/结构检查完成，不能宣布整个模型已被解释或验证。
- 历史快照可能已有旧采集器填入的位置序号，本页只能展示当前保存字段及其证据，不能恢复未保存的原始调度信息。

## 8. 下一切片

接着做用户反馈 13 的前端资产服务端分页和 14 的“加载结构→配置映射→生成”顺序约束；同时调整 6 的长维度名空间。核心语义方向是从所选 Chore/TI 的源代码建立有界读/算/写工作流，分别展示执行关系和转换事实，再以合成黄金数据验证受支持公式，推进 8/15 的教材和迁移契约。
