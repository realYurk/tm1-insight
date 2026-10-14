# Workflow Reconstruction v1

## 1. 产品结果与支柱

主路径改为 Process → Execution Workflow → Cube Reads/Writes → Calculation → Evidence → Export，对应业务逻辑逆向工程与计算语义还原。首页突出“你想理解哪个 TM1 计算流程？”。六个视图在同一工作台中切换；原 Learning、Knowledge、Experience、Codegen、图谱、影响分析等保留在高级工具中。没有增加教材、知识标签或审批流程。

本轮不做目标 Cube 自动选入口、跨 TI 参数替换、Rule/Feeder 计算、实际运行或迁移等价证明。

## 2. 检查过的代码与基线

检查 learning/engine.py、understanding.py、syntax.py、calculation.py、knowledge 模块、ingest/hard_extract.py、parser adapter、dependency/lineage、store 与 TI/图谱路由及测试。

旧学习报告只扩展两层调用；对象关系图与 hard_extract 包含对象级关系，封装启发式不能成为语句级值流证明。已有计算 DAG、源码位置、名称解析、命名参数验证、TaskManager、离线坐标映射与分页缓存可复用。新工作流以源码事实驱动展开，不以索引边或 Bedrock 名称推导计算。

隔离用户目录的基线：473 passed，1 个现有 Starlette/httpx 弃用警告，61.98 秒。

## 3. 实现与文件

- workflow.py：范围 BFS、循环分量、事实分层、计算重建、UNKNOWN、逐 TI 缓存、分页 SQLite 索引和流式 Markdown。
- api/workflow.py、api/app.py：后台任务、进度/取消、源指纹验证、分页详情、按需原代码、JSON / Markdown 导出。
- workflow.html、workflow.js、workbench.css：统一工作台、相关 TI 搜索、六视图、源码定位、分页与窄屏布局。
- base.html、index.html、workbench_home.html、home.js、process_view.html：首页与 TI 入口、主导航、高级工具、静态资源版本。
- learning/calculation.py、understanding.py：复用 DAG，支持安全单常量调用目标赋值链；阻断 Metadata/Data 的零到多记录赋值向后续 Section 被当作确定常量传播。缓存语义版本升级。
- store/calculation.py、store/invocation.py：共享名称目录与命名绑定检查，兼容 Name/name 参数声明。
- learning/engine.py：更新旧学习缓存版本，避免继续复用较强的旧推断。
- tests/test_workflow.py：合成工作流与 API 回归。

## 4. 示例与证据

合成流程 Entry → Step1 → Step2 → Step3 → Compute，包含包装调用、调用闭环及动态目标。Compute 的 Data：

```text
1 nA=CellGetN('Cube_A',vYear,vProduct);
2 unused=CellGetN('Cube_D',vYear,vProduct);
3 nB=CellGetN('Cube_B',vYear,vProduct);
4 nC=nA*nB;
5 CellPutN(nC,'Cube_C',vYear,vProduct);
```

Year/Product 是完整离线维度顺序，vYear/vProduct 是相同的未覆盖参数绑定，重建：

```text
Cube_C[Year,Product] = (Cube_A[Year,Product] * Cube_B[Year,Product])
```

写入行 5 → 赋值行 4 → 读取行 1、3 形成静态表达式依赖；行 2 的 Cube_D 只保留读取事实。改变某个读取坐标后不再输出同一切面的简写。每项保留 Section、行、列及 TI 源码哈希。静态调用不代表执行成功或完成顺序。

## 5. 测试命令与精确结果

所有 pytest 在导入前设置独立临时 TM1_INSIGHT_HOME，不使用真实用户目录。

```powershell
$env:TM1_INSIGHT_HOME=Join-Path ([IO.Path]::GetTempPath()) ('tm1-regression-'+[guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest -q
```

最终完整回归：488 passed，1 个现有 Starlette/httpx 弃用警告，62.88 秒。覆盖深层展开、循环、封装、动态 UNKNOWN、条件、变量依赖、坐标差异/缺失、缓存复用、限定源码查询、分页无需解码整报告、取消、源变化失效和私有导出。浏览器验收覆盖首页发起、六视图、原代码跳转、参数依据；390px 视口稳定布局无横向页面溢出，控制台无错误。JS 语法、差异空白和发布暂存区另行检查。

用户指定 TI 在私有本地模型存在；验证工作流完成、分页与两种导出正常，原始数据库与 WAL 哈希前后一致。真实报告、名称与规模只保存仓库外私有目录，不纳入发布。

## 6. 兼容、数据安全与性能

原 CLI、DuckDB schema、Portable 启动链、历史接口与经验数据保留；无新增必需服务、LLM、向量库或 TM1 写操作。旧 exe 需重新打包才具备新功能，本轮未发布 exe。

默认最多 200 TI / 32 层，可设最多 500 / 64；单 TI 250000 字符 / 5000 DAG 节点，全范围 5000000 字符 / 50000 节点，每类最多 10000 事实。边界显式显示；不为页面读取全库 TI 代码，仅载入全库名称目录及范围内 TI。原代码按 Section、最多 200 行返回，UI 每次 80 行；记录分页最多 100 条，UI 50 条。

相交分析复用同一源指纹的逐 TI 缓存，活跃载荷最多 64 MiB，SQLite 文件页上限 128 MiB；结果与索引缓存预算 256 MiB。源指纹变化失效，暂不支持变更快照之间的逐 TI 精细增量。取消为协作式，在 TI/阶段边界检查，单 TI 解析期间不强制中断。导出隐藏字符串常量，但包含私有对象名，仅供本地保管；原始 Evidence 按需查看，可能包含原字符串。

## 7. UNKNOWN 与明确限制

变量传播限于已有静态定义 DAG；不支持的语法、分支/循环、复杂函数、外部行数据、动态对象及缺失坐标不补造公式。参数只验证显式命名绑定，不应用缺省值、不证明类型、不跨 TI 替换。RunProcess 调用不产生完成顺序证明；缺失封装源码不根据 Bedrock 函数名合成写入效果。

Caller 目录与未绑定语句的索引边标为 STRUCTURAL_UNVERIFIED；真正源码调用和静态值依赖具有代码位置。Cube 两端确认不等于坐标、路径或运行结果完全确认。工作流整体保持 PARTIAL，不声称完整业务理解或数值等价。发现层级是入口距离，不是实际执行时序。

## 8. 下一条纵向闭环

在同一工作台选择一个明确命名绑定的调用，将调用方已支持的标量/坐标表达式以作用域区分的方式绑定到子 TI 的参数使用点；保留双方证据、默认值与覆盖边界。先对分支、循环、重复参数及动态调用输出 UNKNOWN，再扩展受支持的跨 TI 公式。随后增加目标 Cube → 候选写入 TI 的统一入口与人工运行对账契约。
