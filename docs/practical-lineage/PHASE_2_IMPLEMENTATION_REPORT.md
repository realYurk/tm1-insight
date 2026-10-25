# Phase 2：TI 调用与重构研究闭环

日期：2026-10-24。接续用户“继续”授权。分支 `codex/canvas-excellence-04`，保留 Phase 0/1 和此前未提交修改；未提交、推送、合并、回滚或发布。

## 产品结果与复用
用户从 `/graph?ti=名称` 查看本 TI 的直接读写、调用参数/条件、入口 Caller/Chore、独立写入切面、源码证据和可读报告。对应 Lineage & Relationships / Architecture Explorer。

复用 `workflow.build` 的有界调用展开、缓存、循环识别、Calculation、named_bindings、既有任务进度/取消、artifact 分页与 evidence 源码校验。没有修改 Parser、Calculation DAG、值流判定、Snapshot 或数据库 schema。

旧 `graph.html` 把递归 Caller/Callee 名单一律连向中心 TI，容易误读为直接调用。新视图使用 Workflow 的真实 process/target 源码调用端点；入口索引另列，不补造执行顺序。旧模板和 process_graph_rich 等查询能力保留，但 `/graph?ti=` 页面不再使用该扁平投影。

## 文件修改
- `src/tm1_insight/workflow_review.py`：纯展示投影与 Markdown 生成器，读取既有 artifact，不调用解析器。
- `src/tm1_insight/api/workflow.py`：`GET /api/workflow/tasks/{task}/review`，JSON/Markdown/JSON 附件；只读直接 Chore 调度及证据；旧快照无 Chore 元数据/索引时兼容。
- `src/tm1_insight/api/app.py`：原 TI 血缘 URL 使用新只读模板；Cube 入口不变。
- `src/tm1_insight/api/templates/ti_lineage.html`、`api/static/ti-lineage.js`：表格优先、按需源码、高亮/复制/行号、进度/取消、辅助真实调用图、可读与结构化报告。
- `api/static/cube-lineage.js`：复用并公开既有写入操作中文标签；Cube/TI 模板更新资源版本。
- `tests/test_workflow_review.py`：6 个合成测试，含条件/绑定、动态目标、循环、独立写入、源未知、空程序、敏感常量、稳定输出、API/导出及旧调度表兼容。
- `tests/test_human_workbench.py`：保留原回归，旧 Formation DOM hook 断言改为新 TI 页面、范围参数和 Formation 入口。初次完整回归只有该过时展示断言失败，未删除测试规避。
- 更新 `TI_CALL_GRAPH_SPEC.md`、`RECONSTRUCTION_REPORT_SPEC.md`、范围决策和本报告。

## 可核验合成证据
Caller Prolog：`IF(vYear @= 'Member1');ExecuteProcess('Load','vYear',vYear);ENDIF;ExecuteProcess(pDynamic);`。
第一处调用 prolog:1:24；vYear→Load.vYear 经现有参数声明核对为显式绑定，条件未求值；第二处动态目标仍未确认。下游保持 Load→BusinessChild、BusinessChild→Load，不改画为 Caller 直接调用所有节点。
Nightly→Caller 来自合成 chore_runs_process 定义，启用状态未采集则保持未知；调度索引不是实际运行记录。
Unbound Data:1:44：`CellIncrementN(vValue,'Cube_B',pYear,'Member1','Member2')`。源值切面未知；目标 Year 动态、Region=Member1 与 Measure=Member2 固定且来自合成目录验证。之前对 Cube_A 的读取不被当作 vValue 的来源。

## 浏览器验收
独立合成服务 8807；不复用企业服务或正式模型。
- Caller 自动解析显示进度、2 个直接调用观察、显式参数和条件；源码整行展开、语法高亮、复制与行号可见。
- 展开直接 Chore 定义和下游调用表，真实调用端点保持；辅助 Mermaid 离线渲染含静态闭环，动态目标不补造节点。
- 取消按钮可立即取消显示，并实际调用任务 cancel 接口；小任务可能已经完成，不宣称每次都中断后台计算。
- 切换 Unbound 后独立写入和未知源值正确，主表使用“累加数值”，详细函数/变量链在证据层。
- 实际下载 Markdown（2169 字节）、JSON（7781 字节）、Mermaid（206 字节），解析内容验证条件、参数、下游端点、Nightly 和未运行状态。以上为 Caller 合成样例，不外推真实 BP。
- JSON 初次仅靠 HTML download 属性未可靠下载，修复为服务端附件响应头后实测下载成功。

验收产物目录：`<local-acceptance>/ti-review-readonly/`。
包括 `caller-source-and-downstream.png`、`ti-write-source-unknown.png`、导出文件、`safety-result.json`、`performance.json`。
部分离屏 summary 的自动鼠标定位失败，使用键盘 Enter 展开后可见；未将自动定位失败伪装成鼠标验收通过。

## 测试命令与结果
使用 `.venv\Scripts\python.exe scripts/run_offline_tests.py`，全程临时用户目录和外网阻断。
- 专项：`tests/test_workflow_review.py tests/test_human_workbench.py tests/test_workflow.py tests/test_cube_lineage_ui.py -q`：43 passed, 1 warning（8.12s）。
- 修复旧 DOM 断言后全量：1115 passed, 1 warning（130.27s）。
- 交付全量复跑 `-q`：1115 passed, 1 warning（128.56s）。
- 最后兼容性核对 `tests/test_workflow_review.py tests/test_cube_lineage_ui.py -q`：16 passed, 1 warning（3.43s）。
- 警告为既有 Starlette/httpx 弃用提示。Node 语法检查、git diff --check 通过（仅 Git CRLF 转换提示）。

## 数据安全、兼容与性能
合成数据库前后 SHA256 相同；无工作区/设计写入请求，记录到 8 个 Workflow 任务请求与 1 个取消请求。局部派生分析缓存写入独立测试 home，绝非正式 DuckDB/Snapshot。
未连接 TM1、未执行 TI/MDX、未读取业务单元格、未上传企业源码或改写正式库。源码仅按需取本地 process 文本。
保留原 `/workflow`、Workflow JSON/Markdown 和 Formation 加工证据入口，未改代码生成、Windows 启动与 Portable 依赖；未重新打包 Portable。
缓存无需调整解析版本：新增报告读取旧 Workflow artifact，不改变解析事实。每类表最多 200 条，写入 80、值依赖读取 160；图 24 节点/30 调用。超预算明确说明，不把局部视图当全模型。
Unbound 已缓存 review 一次请求 66.46ms、JSON 2989 字节；仅本机合成小模型，非大型模型/FPS 结论。

## 已知限制与建议
Caller 仅有索引时不核对其条件/参数，需进入调用方解析；直接 Chore 定义不涵盖间接最初入口。参数未跨 TI 代入，条件/循环、动态名称、源行变量、完整 View/SQL/CSV 字段、清空/权重/Rule/Feeder 运行行为仍有边界。
没有真实 BP/ACT/Step2 验收，未将合成案例冒充企业成果。复杂辅助调用尚未做源码效果折叠，不按 Bedrock 名称猜用途。
下一条最有价值的工作是：用用户单独指定的本地快照只读核验一条实际 TI 的报告、补齐来源元数据缺口，并保持运行验证与静态推断分开；不自动增加设计器或新解析引擎。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
