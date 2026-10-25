# 验收记录

日期：2026-10-25。所有本轮数据为独立合成 fixture；未用合成结果冒充企业 BP 验收。

## 自动化

- 开始时相关基线：21 passed，1 warning，4.83s。
- 最终专项：`.venv\Scripts\python.exe scripts/run_offline_tests.py -q tests/test_reconstruction_readiness.py tests/test_cube_lineage_ui.py tests/test_workflow_review.py`：28 passed，1 warning，4.39s。
- 扩展相关集（readiness、human_workbench、functional_flow、cube_lineage_ui、workflow_review）：52 passed，1 warning，8.67s。
- 完整回归：`.venv\Scripts\python.exe scripts/run_offline_tests.py -q`：1131 passed，0 failed，0 skipped，1 warning，138.46s。
- 用户授权提交后复核：专项三文件加 tests/test_publication_guard.py：30 passed，1 warning，4.23s。仅将独立 Node 测试脚本扩展名从 .cjs 调整为发布检查已允许的 .js，并更新引用，没有放宽发布检查规则或改动产品逻辑。
- warning 为 Starlette TestClient/httpx 弃用提示。Node 语法检查与 git diff --check 通过；Git 提示已有 LF/CRLF 转换，不是差异错误。

## 16 个场景对应证据

| 场景 | 验证位置 |
|---|---|
| CellGet 明确值依赖、独立常量反例 | test_cube_lineage_ui 的独立读写/无关读取测试；readiness NativeView 常量反例 |
| NativeView 无 CellGet | test_native_view_without_cellget_has_separate_declaration_and_value_proof；实际浏览器 ViewLoad |
| 多 TI、多个独立写入 | test_cube_projection_multiple_ti_rule_and_self_loop、test_multiple_reads_and_writes_are_independent；浏览器关系回填 |
| Rule 与 Feeder 不混淆 | 既有 engineering_workbench、Rule suites；Cube 投影验证 |
| 自环 | Cube Self fixture、浏览器 Mermaid |
| 多层调用 | workflow_review 参数/端点测试；浏览器 Caller→Load→BusinessChild，保留循环 |
| 动态 ExecuteProcess | 同上，目标未确认 |
| 已记录 Chore | Nightly→Caller 步骤 0，浏览器展开确认 |
| 参数缺失/不确定 | Caller 显式命名绑定与动态调用无命名参数分别呈现 |
| Variables 缺失 | test_variables_missing_retains_declaration_not_value_dependency |
| 关系/报告预算 | 既有 graph budget 测试与新控制器 budget 测试 |
| 部分核对导出 | 浏览器预算 1，完整 1/部分 1/未核对 2；下载并解析 JSON |
| 只读退出 | 浏览器历史工作区点击、展开、布局、缩放及退出，无 dialog、无保存请求，哈希不变 |

另外验证 MDXView/UNKNOWN 布局、陈旧哈希、动态覆盖、旧快照缺元数据表、250000 字符预算及模型不匹配 409。取消、部分失败、迟到响应和 409 中止通过真实 shipped JS 的延迟 Mock 控制器验证；不将 Mock 当成 TM1 运行验收。

## 实际浏览器验收

使用 CUA 操作独立服务 localhost:8809：

1. Cube_B 默认 4 条 Cube 关系，Rule/候选分开。预算 1 请求复用后完成 2/10 关系内机制；预算 20 从空缓存发起 9 个唯一请求，完成 10/10，4 条关系核对完毕。
2. ViewLoad 第一写入显示 Cube_A/Input 的 vValue 值列与源动态坐标；第二常量写入不生成该值依赖。
3. 点击关系中的 TI 研究链接，URL 固定 model；TI 页没有 CellGet 仍展示声明来源和 3 个变量，展开表中 vValue 为值列，维度列与值列分开。
4. Caller 页展开直接调用、命名参数、IF、动态目标、间接调用和 Nightly 调度，未声称执行顺序。
5. 有效历史工作区恢复后点击 Cube_A、展开得到 3 对象/2 关系，缩放、平移、自动布局、方向与适应后退出，无保存弹窗。另一个错误引用的合成工作区被拒绝且原文件保留；原因是测试夹具只改 snapshot 未重算引用，另建有效夹具后完成正例，未修改产品语义来绕过验证。
6. Cube 辅助 Mermaid 自环可见，1:1、方向切换、适应可操作。滚轮、隐藏容器、resize、dispose 由既有 test_readonly_report_view 自动化验证；本轮未新增大型图引擎，也未完成超大型模型/所有分辨率的人工验收。

截图保存在本机独立验收目录 `C:/Users/Administrator/.codex/visualizations/2026/10/13/01a134f4-6232-7a30-8869-bb66fb98bbc3/reconstruction-readiness/`：cube-partial-budget.png、cube-full-coverage.png、view-row-dependency.png、ti-native-view.png、ti-calls-and-schedule.png、readonly-expanded.png、cube-mermaid-self-loop.png。

## 导出、性能与安全

实际下载文件已复制到上述验收目录：cube-summary.md 8260 bytes（INDEX_SUMMARY、inspected=[]）；cube-partial.md 32363 bytes（预算截断、2 条已核对记录）；cube-full.md 109442 bytes（4 条关系完整核对）；ti-view.md 7735 bytes；ti-view.json 11986 bytes（ViewLoad、reads=[]、view_sources=[Cube_A]）。不同范围体积不可当成同一模型的性能前后对比。

合成 ViewLoad scoped writes API 三次耗时 50.98 / 28.12 / 28.02 ms，响应 7713 bytes。只说明此小型夹具，不外推企业大模型性能。队列最大 20 个唯一请求；单 TI 先检 250000 字符预算。报告仍可能包含较大的局部表达式树，本轮不重构序列化。

合成 DB、原历史工作区、有效历史工作区 SHA256 均与各自浏览前一致。请求日志只有既有 graph 查询和 workflow 分析任务 POST，没有 workspace/design 保存请求。正式 collections、DuckDB/WAL 未访问或修改。分支保持 codex/canvas-excellence-04；没有 commit/push/merge。验收结束后关闭本轮浏览器页，核实命令行后仅停止本轮创建的 8809 服务 PID 16072；未停止其他服务。

## 未完成或不能推定的结论

浏览器端取消不能抢占已经运行的单个 Python 解析；停止后不发后续请求、不采纳迟到结果。未人工注入服务器失败来替代自动化故障测试。浏览记录不持久化为研究管理系统；离页需导出。缺失 VIEW 布局、动态 MDX、运行时值和条件仍未证明；静态依赖不是迁移等价。

可以进入模块级重构规格的有界证据整理，暂不能进入无需人工验证的自动迁移。

开发验收记录中的“未提交”描述对应当时状态；随后用户明确授权本地 Git 提交。提交保持当前分支，不执行远程 push、merge 或发布。
