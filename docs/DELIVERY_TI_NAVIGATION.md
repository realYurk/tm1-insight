# TI 定位与源码查证闭环（2026-10-13）

## 1. 产品结果、范围与验收

支柱：Reverse Engineer / Prove。减少从几千个 TI 中定位候选、核对原始代码、切换候选时丢失上下文的成本。

本轮交付用户反馈 1、2、3、4，并加固 9 的状态识别和数据保护。非目标：业务公式推断、模块提取新引擎、全站视觉重做、真实 TM1 执行或迁移等价证明。

验收：默认名称匹配；显式选择代码检索；结果提供可定位的段/行/列；详情页可搜索全部 TI；分页没有 500 条截断；返回列表保留范围和页码；逐行变量表；代码高度随可用视口调整；Local/Demo 切换不改变原库字节；过期源码位置拒绝定位。

根目录新增与治理文件包逐字一致的 `PRODUCT_CONSTITUTION.md` 和 `AGENTS.md`，让后续开发继承约束。原治理文件包保留。

## 2. 已核对的代码事实

- `store/queries.py::search_processes` 原来同时在名称与四段代码执行 ILIKE。调用者、注释与字符串都可能命中，旧 UI 没有给出原因。
- `api/app.py::processes_page` 原来先取最多 500 个结果再在 Python 分页，超过 500 的数量与后续页面丢失。
- `process_view.html` 原来使用变量矩阵与 68vh 固定代码高度；返回列表仅保存词和页码，未区分数据源。
- `datasource.py::load_demo_data` 原来在独立 Demo 目录 DROP/重建表，未发现删除真实 Local 库的代码路径。但重复切换会重建 Demo 本身。
- Demo 身份原来仅按目录判断；该目录旁的其他命名 DuckDB 文件会被误标 Demo。
- 首页 `store.db_path` 实际是字符串，却调用 `.exists()` / `.stat()`，异常被吞掉，时间显示未知。
- 当前源码配置只读检测为 Local。未能连接默认 8000 端口的运行服务，因此没有复现用户旧页面的具体状态，也不据此声称历史未丢数据。

## 3. 最小设计与代码文件

- `store/queries.py::search_process_page`：name/code/all 三种显式范围，字面量、不区分大小写匹配；精确名称、前缀、包含、代码依次排序；COUNT + LIMIT/OFFSET，最多返回 100 项；只有显式代码搜索读取当前页源码。
- `api/app.py`：列表复用查询；新增 `/api/processes/search`；验证范围、长度、分页参数；返回私有路径的哈希指纹；数据源变化返回 409；代码证据链接携带指纹，旧行号失效时拒绝定位。旧 `/api/search` 保留原行为，兼容已有图入口。
- `templates/processes.html`：搜索范围、命中类型、源码摘录及真实分页。
- `templates/process_view.html`、`templates/process_switcher.html`、`static/process-search.js`：按需打开原生 dialog；25 项分页；防抖、取消旧请求、丢弃过期响应；源码锚点；关闭/ESC 恢复焦点；按源指纹隔离会话上下文；ResizeObserver 调整代码高度。
- `static/workbench.css`：逐行变量表、响应式对话框、源码定位高亮；保留代码区原有宽度和全站主题。
- `templates/chore_view.html`：兼容返回 TI 列表的范围与来源校验，没有重做 Chore 布局。
- `datasource.py`：按准确 Demo 数据库文件识别；现有数据库不可读时不自动改选 Demo；Demo 建库加锁、临时目录构建后切换；已有可读 Demo 只复用；不可读文件拒绝覆盖。
- `templates/base.html`：服务端直接输出来源，浏览器无缓存刷新来源；状态获取失败保留本页初始状态并给出说明。`api/app.py` 修复首页文件时间读取。
- `scripts/check_publication.py`：仅增加两份根目录治理文件到产品白名单，保留敏感数据检查。
- 测试：`tests/test_process_search.py`、`tests/test_datasource.py`、`tests/test_publication_guard.py`。

## 4. 可复查的合成证据

虚构调用者 `Cub.Example.Task.Caller` 的 Prolog：

```text
1  # source lookup only
2  ExecuteProcess('Cub.Example.Attachment.Load.From.CSV');
3  ExecuteProcess(pDynamicChild);
```

搜索目标 TI 完整名称时：name 仅返回目标；code 返回调用者，证据为 Prolog 第 2 行、第 17 列；all 返回两项并区分原因。点击代码证据跳转并高亮第 2 行。

搜索 `pDynamicChild` 提供第 3 行原文。现有 resolver 返回 unresolved；本功能不尝试确定其被调对象，也不写入 `process_calls_process`。即使命中注释或字符串也只称为文本命中。没有建立新的调用、值流或业务关系。

变量表中的 UNKNOWN 表示未提取到赋值。现有词法提取器可能截断长表达式、保留多次赋值中的某个片段，不能据此声明运行时值或业务含义。

## 5. 测试与浏览器验证

测试通过新的临时 `TM1_INSIGHT_HOME` 运行，既不读取项目 `.env`，也不写真实业务库：

```powershell
$tm1TestHome = Join-Path ([System.IO.Path]::GetTempPath()) ('tm1-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tm1TestHome | Out-Null
$env:TM1_INSIGHT_HOME = $tm1TestHome
.venv/Scripts/python.exe -m pytest -q
```

- 修改前：334 passed，1 warning。
- 最终复验：361 passed，1 warning，26.09s。唯一原有 warning 为 Starlette TestClient 对 httpx 的弃用提醒。
- 覆盖：名称/代码分离、排序、字面量 `%`/`_`/引号/中文、四个源码段、多行文本位置、Unicode 列号、1128 项分页、参数上限、HTML 转义、动态 unresolved 不新增关系、来源变化/过期证据拒绝定位、Local→Demo→Local 两库哈希不变、损坏文件保留、建库失败无残留活动文件。
- 浏览器采用独立合成模型：名称与全文切换、证据行高亮、详情切换、同页选择关闭窗口、ESC/焦点恢复、返回列表保留范围、快速改词、25 项分页及第二页 26–50。
- 1536×864：代码区 top=204.8px、height=643.2px、bottom=848px，距底部 16px；1920×1080 下 bottom=1064px，同样距底部 16px。390×844 的深色窗口下对话框完整位于视口内。均未出现整页横向溢出。
- 合成截图保存于本次本机可视化附件目录，不包含真实模型源码或凭据。
- `node --check src/tm1_insight/api/static/process-search.js` 通过；`git diff --check` 通过；对本轮 18 份工作区变更执行发布保护检查通过（未暂存，不用零暂存文件的检查冒充已扫描）。治理副本按字节核对一致。未执行完整 Ruff 检查：当前环境未安装 Ruff。

## 6. 安全、兼容与性能

真实本地模型已完成只读复查，文件大小、mtime 和流式 SHA-256 一致。真实模型规模与本机性能测量记录保留在本机，不进入公开仓库。

合成夹具验证完整名称的 name/code/all 检索分别返回 1/1/2 项，代码命中带原始位置。请求性能需要在目标硬件、指定规模和冷/热缓存条件下分别测量，查询层或进程内 TestClient 耗时不等于浏览器端到端延迟。

无新依赖、无 TM1 网络访问、无 TI 执行、无数据模式迁移、无提交或发布。分页限制返回数据和浏览器 DOM；代码查询仍需要扫描候选源码，尚未引入全文索引，也没有宣称服务器查询可中途取消（AbortController 取消浏览器请求）。

## 7. UNKNOWN 与未完成项

- 当前文件指纹由路径哈希及文件/WAL 状态生成，用于失效检测，不是不可变快照 ID 或运行证据。
- 代码检索展示每个进程第一处命中及最多 240 字符摘录；详情页现有代码搜索可继续查其他位置。
- 名称搜索不能证明哪个 TI 写入某 Cube；文本出现也不能证明调用或值流。完整公式、参数传播、动态对象与 Rule/Feeder 语义尚待进一步实现。
- 首页显示时间来自文件 mtime，不能视为采集时间或真正历史快照管理。
- Local 标签异常只修复了可证实的识别/状态问题；用户旧运行实例需用新源码重启核对。旧 exe 未重新打包。

## 8. 下一纵向切片与反馈队列

下一项建议：以独立 Chore 双栏入口为起点，选择一个有界工作流，展示有证据的调度步骤与每一步的读/算/写语义。执行关系与数据转换分开；保留动态 UNKNOWN；导出 JSON/Markdown；用合成黄金数据校验一种受支持公式，随后才能讨论迁移等价。

其他反馈保留为后续任务：

| 用户编号 | 状态 / 下一验收重点 |
| --- | --- |
| 1–4 | 本轮实现定位、切换、代码高度、变量表、搜索范围与命中证据 |
| 5、6 | 维度浏览的切面价值、长维度名空间分配，尚未改动 |
| 7、16 | 系统菜单归组、取消误导性空快照比较，接入真实版本选择后再开放历史对比 |
| 8、15 | 用工作流/计算证据驱动模块和教材，优先于继续增加泛化总结 |
| 9 | 本轮状态与文件保护加固；未复现用户旧实例/历史问题 |
| 10 | 采集与扫描分阶段真实进度；在线采集还需新快照构建失败保留旧库 |
| 11、12 | 全站配色与工作台首页，待核心工作流信息架构确定后设计 |
| 13 | 前端资产独立分页，尚未改动 |
| 14 | 代码生成按加载结构→映射→生成的顺序约束，尚未改动 |
| 17 | Chore 独立双栏下一切片；本轮只完成 TI 临时搜索窗口 |
