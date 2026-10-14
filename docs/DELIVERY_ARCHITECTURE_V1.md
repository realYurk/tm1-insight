# Architecture Explorer v1

## 1. 产品结果与四层约束

PRODUCT_CONSTITUTION.md 正式确立模型资产、关系与血缘、系统架构探索、人工业务解释四层；AGENTS.md 同步约束。核心体验是数据对象 → 加工步骤 → 结果对象。技术状态、哈希、日志、Bedrock 调用进入展开的实现与诊断。保留白蓝主色，主导航为模型资产、数据血缘、系统架构、代码生成。

本轮交付从准确 TI 名称出发的完整工作台。Cube/Chore/关键词模块入口尚未实现；名称片段只搜索候选 TI，展开真实依赖不受入口前缀限制。原接口、CLI、数据与历史保留；未扩展教材或代码生成模板。

## 2. 复用和检查的代码证据

检查现有 Workflow BFS、Calculation DAG、understanding/syntax、DuckDB schema/queries、Dimension Explorer、任务缓存、TI/Cube/Chore/图谱路由、首页及代码生成页面。复用现有 Workflow 与参数绑定，不建立第二套执行或计算引擎；复用解析器识别原语与源码位置，复用 DuckDB 关系索引寻找局部 Rule/Caller/Chore 候选。

Caller 候选必须再核对源码调用；Rule 目录候选必须核对真实 DB 调用。Chore 使用离线 chore_runs_process 元数据证据，标明不证明启用或实际运行。关系保持结构、读写、调用、静态值依赖的分类；未进行运行验证。

## 3. 实现与文件

- PRODUCT_CONSTITUTION.md、AGENTS.md：四层架构与默认解释原则，禁止产品内集成 AI 服务。
- architecture.py：已有工作流的局部架构组装、原语语义折叠、Cube 维度模型、Rule/Feeder 引用、Caller 源码验证、Chore 元数据、确定性架构导出。
- api/architecture.py、api/app.py：架构任务、来源失效检查、进度与取消、分页、按需成员与源码、证据及导出。
- architecture.html、architecture.js、workbench.css：首页同色的架构工作台、数据加工步骤、实现展开、成员表格与分页。
- base.html、index.html、workbench_home.html、home.js、process_view.html：四个主入口、TI 架构入口、旧工具保留。
- workflow.py、api/workflow.py：复用分页制品能力与源码校验，旧调用签名保持兼容。
- understanding.py、calculation.py、engine.py：补充视图/子集原语引用，更新受影响缓存语义版本。
- tests/test_architecture.py、README.md、本交付文档：可执行验收与使用说明。

## 4. 可核验的合成模块

Nightly Chore → Caller → Load；Load 调用 BusinessChild，后者回调 Load，保留调用闭环。

- Cube_A 维度顺序：Year → Product。
- Cube_B 维度顺序：Year → Region → Measure。
- Load 显式绑定 VIEW 数据源 Cube_A，源码创建 SourceView，创建 Product 子集、插入成员并绑定 View。
- Load 显式调用辅助 TI，辅助源码为 ViewZeroOut(pCube,pView)。通过未被覆盖的声明参数及显式字面 Cube 参数，将清理 Cube_B 的观察归入 Load。未推导实际切片或写入前后执行证明。
- Data 中 n=CellGetN(Cube_A,...); result=n*2; CellPutN(result,Cube_B,...) 建立真实赋值链，可展示不同坐标组合的表达式与原行列。
- 另一个属性映射写入无法完整重建，保留具体待核对说明。
- Journal 的读写位于明确的 Logging Region，默认不进入业务输入、输出或公式；实现证据保留。
- RuleOutput 的 Rule 与 Feeder 语句引用 Cube_B，保留不同类别及源码位置；未宣称完整 Rule/Feeder 语义已还原。
- 动态调用不产生猜测对象。名称包含 clear 的空辅助 TI 不产生清理效果，准备操作不产生值流。包装参数被重赋值时，外部传入值不能再作为清理目标证明。

点击加工步骤的“查看实现”可查参数、操作、技术调用、诊断和四个 Section 原代码。数据模型按需显示成员、属性定义、子集与原始汇总权重。独立 Hierarchy 名称、属性值与指标维角色缺失时明确说明。

## 5. 测试与浏览器结果

所有 pytest 在导入前使用新的临时 TM1_INSIGHT_HOME：

```powershell
$env:TM1_INSIGHT_HOME=Join-Path ([IO.Path]::GetTempPath()) ('tm1-architecture-test-'+[guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest -q
```

基线 488 passed，1 个现有 Starlette/httpx 弃用警告，62.99 秒。最终完整回归 497 passed，1 个同类既有警告，59.41 秒。

测试覆盖模型维度、语义折叠、不同目标粒度、日志排除、调用闭环、Rule/Feeder、Caller/Chore、动态引用、包装参数覆盖、未实现包装反例、局部源码 SQL、相同输入的 JSON 字节确定性、私有导出、成员分页、来源变化失效和协作取消。既有 Workflow、CLI、代码生成等全套回归通过。

浏览器检查首页发起、默认加工链路、辅助源码跳转、Cube 模型、成员表格、Chore 分页、代码生成一级入口；控制台无错误。390px 视口下页面宽度 375px，无横向溢出；测试后重置视口。

## 6. 安全、兼容与性能

只读验证用户指定本地 TI，工作台、各分页和 JSON/Markdown 导出可用；原始 DuckDB/WAL SHA256 前后一致。真实名称、源代码、报告和度量保存在仓库外私有目录，不进入公开提交。

合成大型目录：3004 TI、3004 Cube、10004 Dimension。局部组装约 0.171 秒，仅加载 4 个不同 TI 的源码，没有读取无关 TI 源码；Python tracemalloc 峰值 7.62 MiB，不含 DuckDB 原生内存，不能作为总进程内存或所有企业模型的性能承诺。

默认 100 TI/16 层，最多 500/64；沿用 Workflow 单 TI 250000 字符/5000 DAG 节点、全范围 5000000 字符/50000 节点及分类事实上限。最多组装 150 Cube、600 Dimension、150 Rule 所属 Cube、500 条范围内调度与最多 100 条验证 Caller 的调度。Caller 验证最多 20 个，额外源码共 1000000 字符；Rule 单对象 250000 字符、合计 5000000 字符。证据超过 30000 条时明确要求缩小范围，不发布截断后伪完整资料。

架构记录分页，成员按需每页 50 条，源码 UI 每页 80 行。架构成员读取复用现有 DuckDB JSON 查询，不额外建立全库维度索引；复杂大维度可进入现有 Dimension Explorer 使用索引能力。取消在 TI、元数据对象和阶段边界检查，单对象解析/SQL 内不强制中断。

复用原同快照逐 TI 缓存，架构结果/索引缓存预算 256 MiB。模型变化失效；暂不做跨变更快照的精细增量。未增加必需服务、第三方运行依赖或 AI；未改真实模型 schema，未执行 TM1，未重新发布 Portable exe。

## 7. 导出契约、未知与限制

Schema 为 architecture-1，含 module、entry_points、cubes、dimensions、processes、rules、chores、execution_relationships、data_relationships、transformation_steps、input_outputs、evidence、unresolved_dependencies、migration_notes。JSON 键排序，关系按确定顺序生成；不包含时间戳或缓存命中率等易变字段。JSON 额外保留按 TI 作用域区分的计算 DAG；Markdown 先展示模型与加工步骤，再附分类关系、元数据和技术证据。

源/目标读写观察不代表每个读取都参与所有写入；已追溯的静态表达式关系单独标记。辅助效果仅对原始源码原语与一层显式、未覆盖参数绑定进行确认，不按 Bedrock 名称推导 COPY/TRANSFER。多层包装动态值、条件、视图实际成员、变量别名数据源、外部文件/SQL 来源与完整计算语义仍有缺口。

Cube 的读取/写入 TI 是本次范围内观察，不宣称全库完整清单。Rule/Feeder 仅还原字面 DB 引用与语句归属，不生成完整计算 AST 或汇总规则。独立层级名称、业务维度含义、指标维、属性值缺失时不推断。导出维度部分为结构与采集状态，不包含全量成员/权重迁移包；需要配合按需证据与后续模型提取。

默认隐藏字符串常量；原代码仅通过本地证据接口查看。导出含私有对象名，仍需本地保管。架构整体保持未完成验证状态；没有自动生成业务故事、最终关系表或迁移等价结论。

## 8. 下一条纵向切片

优先把 View 数据源赋值链、Subset 成员选择与属性映射纳入现有作用域/变量定义链，使一条真实源切面 → 目标切面的映射可验证；继续保留被覆盖参数、条件、动态成员的边界。随后增加 Cube/Chore 候选入口，沿证据组装同一个架构 Schema。业务名称和计算口径留给人工确认层。
