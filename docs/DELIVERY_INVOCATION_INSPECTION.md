# 单次子 TI 参数检查（2026-10-14）

## 1. 产品结果与支柱

对应反馈 8 / 15，推进 Reverse Engineer / Prove / Modernize：从 TI 计算检查选择一个调用点，核对调用方表达式、显式参数绑定、子 TI 中仍可追踪的使用位置、原计算定义及读写坐标。

这是一个调用点和一个子 TI 的静态检查闭环，不是完整跨过程值流、功能模块提取或迁移等价证明。不从对象名称推断业务目的。

验收：调用方读取证据与子 TI 使用证据分别保留；值、坐标和 Cube 表达式区分；动态调用不猜目标；重复或缺失参数不猜绑定；参数覆盖及未知函数阻断追踪；模型变更使旧链接失效；不修改源库。

## 2. 检查到的代码证据

- `learning/understanding.py` 已识别 ExecuteProcess / RunProcess 及命名参数，但参数表达式只是文本，没有接到使用位置。
- `learning/calculation.py` 已有位置敏感赋值 DAG、算术定义链和保守控制合并；原调用记录只保留独立观察。
- `store/calculation.py` 已对 DAG 读取与写入坐标使用完整维度顺序核对，并保留缺失结构 UNKNOWN。
- `/calculation` 已提供源码锚点、来源指纹、私有导出和预算。本轮扩展这些事实，不另建全模型图引擎。

## 3. 实现与文件

- `learning/calculation.py`：在调用位置解析实际参数表达式，记录局部定义/读取/未知项；为写入 Cube 表达式增加节点；节点裁剪包含调用参数根。名称字符串只保留哈希用于声明匹配，不输出未知原参数名。调用方读取坐标中的未知项单独保留。
- `store/invocation.py`：只加载一个选中调用点和一个字面目标子 TI；按当前解析器的不区分大小写名称匹配声明，检查重复及完整配对。建立 `write_value`、`write_coordinate`、`write_target`、`read_coordinate`、`read_target` 使用记录，并保留两侧源码位置、子 TI 原公式和条件边界。
- `api/app.py`：`/invocation` 与 `/api/invocation/export`。复用查询前后模型指纹校验，来源参数必填；过期来源 409，不存在的 TI / 调用点 404，无效索引 422；导出禁止缓存。
- `templates/calculation.html`、`invocation.html`、`base.html`、`static/workbench.css`：调用表增加「核对参数」；每个参数单独成行，左右展示调用方依据和子 TI 使用；可跳到原代码或子 TI 写入点。窄屏改上下布局，侧栏高亮 TI。
- `tests/test_invocation.py`：静态绑定、读写角色、动态名称、重复/未知/敏感参数、缺失配对、覆盖、分支、未知函数、同一行调用、循环调用边界、坐标未知、来源与数据安全。

JSON 使用 `ti-invocation-inspection-1`，范围 `one_call_one_child_no_substitution`；两边源码哈希与当前模型指纹保留。原计算导出增加调用参数及目标节点字段，原页面和接口继续可用。

## 4. 合成证据示例

```text
# Entry / Prolog
amount=CellGetN('Input',pDept);
ExecuteProcess('Child','pAmount',amount,'pRate',2,'pDept',pDept,'pTarget',pTarget);
ExecuteProcess(pDynamic);

# Child / Data
value=pAmount*pRate;
CellPutN(value,'Result',pDept);
CellPutN(1,pTarget,pDept);
```

`pAmount ← amount` 连接到调用方的 Input 读取和子 TI 的 `value = pAmount * pRate` 原定义。两边仍是分别存在的事实，没有生成替换后的跨过程公式。

`pDept` 出现在目标坐标；`pTarget` 出现在目标 Cube 表达式，Cube 仍为 UNKNOWN。即使传入字面 Cube 名称，本轮也不自动替换子 TI 中的动态目标。`ExecuteProcess(pDynamic)` 只展示未知边界，不加载猜测的子 TI。

子 TI 如果覆盖 pAmount，或把它传给未支持的函数，就不再声明存在可追踪的写入使用链。没有使用记录不能解释为参数无用。

## 5. 测试与验证

pytest 均使用独立临时 `TM1_INSIGHT_HOME`。

- `.venv/Scripts/python.exe -m pytest -q`：471 passed，1 个既有 Starlette/httpx 弃用警告。
- `.venv/Scripts/python.exe -m pytest tests/test_invocation.py -q`：16 passed，同一警告。
- `git diff --check`：通过。
- 独立合成模型浏览器验证：调用表入口、两侧源码位置、子 TI 原公式与写入点跳转、动态调用 UNKNOWN；390px 视口无横向溢出，控制台无错误。
- 当前真实离线样本：页面及 JSON 导出可用，源库与 WAL 的 SHA-256 前后相同。私有名称、路径和测量结果未纳入公开提交。此检查不证明数值正确或迁移等价。

## 6. 兼容、数据安全与性能

不改数据库模式、不增加依赖、不执行 TI、不连接服务器、不写源库。复用单 TI 250000 字符、单语句 1000 token、5000 节点及 2000 条调用观察预算；一次最多检查两个 TI，不递归加载其调用者或被调用者。参数使用记录上限 2000，达到预算明确标记 PARTIAL。

页面展示前 50 个参数，每项定义/读取/使用/未知项最多 20 条，读取坐标最多 20 项；预算内完整节点与位置见 JSON。Markdown 是有界概览，每类记录有展示上限，总计最多 2000 行并说明截断。

参数缺省值不参与计算或导出；字符串常量隐藏，敏感参数不展开；私有对象名仍需本地保管。模型指纹覆盖来源变化，不能代替历史快照版本管理。参数声明的变化也由模型来源指纹保护。

## 7. UNKNOWN 与限制

仅展开字面名称且存在于目录的 ExecuteProcess；别名目标、动态调用、RunProcess 和缺失对象均不展开。类型兼容、缺省输入、返回码、异常路径、实际运行次数、数值、规则/馈送、目标原值、清理范围和并发语义均未验证。

参数使用是受支持定义链中的静态观察。分支、循环、重复记录及覆盖可能导致保守漏报。不同 TI 的节点编号只在各自节点表有效；本轮不合并两张 DAG、不替换参数、不证明调用形成值流。

## 8. 下一项纵向闭环

围绕这一个入口与子 TI，建立人工确认边界的模块清单：必需 Cube / 维度、外部参数、读写切面、清理与覆盖策略、缺失语义、源码证据及合成验证样例。先使模块边界可复查，再接数值测试和迁移契约，不用通用业务文字替代计算事实。
