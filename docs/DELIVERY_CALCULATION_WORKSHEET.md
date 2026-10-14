# 单 TI 计算定义检查（2026-10-14）

## 1. 产品结果与支柱

对应反馈 8 / 15，支柱 Reverse Engineer / Prove / Modernize。交付最小闭环：选中 TI → 选择写入点 → 核对定义、读取依赖、目标坐标 → 打开源码 → 保存私有检查材料。

目的在于把“含乘除链”等信号推进为可逐项核对的计算事实。本轮不宣称完成跨过程工作流、业务模式提炼、模块抽取或迁移等价证明，也不自动给公式赋予业务含义。

验收条件：两源算术定义链保留来源位置和运算结构；无关读取不成为写入依赖；动态目标与不支持的语法明确 UNKNOWN；不改动源库；旧分析接口兼容；长列表分页和计算预算有边界。

## 2. 检查到的代码证据

- `learning/syntax.py` 已提供分段词法语句与调用定位，原位置只有行号。
- `learning/understanding.py` 已提供控制结构及保守的对象名解析。旧公式候选属于词法信号，不能证明完整算法。
- `store/schema.py` 的 Cube 维度计数与 `cube_has_dimension.dim_order` 可核对位置，但没有运行时坐标值。
- `api/learning.py`、`static/learn.js` 提供分页学习结果；TI 详情已有源码分段及行锚点。复用这些入口，不新增侧边栏分类。

## 3. 实现与文件

- `learning/calculation.py`：受限算术语法 DAG 与位置敏感的使用/定义链；普通数值、参数、赋值、括号、一元正负、四则与安全除法符号、显式 CellGetN/S。只保留可达节点；未知函数和控制合并处保守停止。
- `learning/syntax.py`、`understanding.py`：补充行列/偏移位置，增加可选的日志区域分析。旧调用默认过滤行为保持不变。
- `store/calculation.py`：只读选中 TI，使用完整维度顺序和准确参数数量匹配读写坐标；缺失、重复或断续的结构不猜测对齐。生成 JSON 所需展示信息与 Markdown。
- `api/app.py`：`/calculation` 与 `/api/calculation/export`，来源指纹前后校验；过期来源 409，缺失对象或选中点 404。导出要求来源参数，响应禁止缓存。
- `templates/calculation.html`、`process_view.html`、`static/workbench.css`：写入点侧栏、来源 → 公式 → 目标、逐行变量表、坐标与 UNKNOWN、源码链接、独立调用边界。每页 50 个写入点；系统前缀默认隐藏并可显式包含。窄屏上下布局。
- `api/learning.py`、`static/learn.js`：学习结果增加来源绑定的「核对计算定义」，旧教材来源不匹配时要求重新分析。
- `tests/test_calculation.py`、`test_calculation_api.py`、`test_datasource_api.py`：语义、来源隔离、隐私和旧入口回归。

无数据库模式变化，无新增依赖。源码 hash 包含分段边界；模型指纹保护当前来源。字符串常量隐藏，目录内已知对象名可显示；敏感变量名停止追踪。导出仍含私有对象名称，应留在本机。

## 4. 合成证据示例

```text
base=CellGetN('Input',pDept);          # data:1
rate=CellGetN('Driver',pDept);         # data:2
amount=base*rate/100;                 # data:3
CellPutN(amount,'Result',pDept);      # data:4
If(pMode@='Dynamic');
CellIncrementN(unknownValue,pTarget,pDept);
EndIf;
ExecuteProcess(pChild);
```

检查第一个写入点显示 `amount = base * rate / 100`，其使用的定义分别链接到 data:3、data:1、data:2。Input / Driver 的读取属于该定义链；Result 的第一个坐标只有在完整目录确认时才映射到 Dept。

第二个写入点保留动态目标 UNKNOWN、未定义的 unknownValue、未求值的条件路径。`ExecuteProcess(pChild)` 是独立调用观察，既不展开也不转换为值流。以上均未执行，不能证明输入数值、最终结果或分摊业务含义。

## 5. 测试与验证

- 隔离临时 `TM1_INSIGHT_HOME` 下执行 `.venv/Scripts/python.exe -m pytest -q`：454 passed，1 个既有 Starlette/httpx 弃用警告。
- 学习入口集成后执行 `.venv/Scripts/python.exe -m pytest tests/test_calculation.py tests/test_calculation_api.py tests/test_datasource_api.py tests/test_understanding.py -q`：55 passed，同一警告。
- `node --check src/tm1_insight/api/static/learn.js` 和 `git diff --check` 通过。
- 浏览器合成模型验证：TI 入口、学习结果入口、计算定义、源码行跳转、动态目标 UNKNOWN、390px 窄屏无横向溢出；未观察到控制台错误。
- 本地真实离线样本只读检查：重复页面与导出可用；源库及 WAL 的 SHA-256 前后相同。私有对象、测量结果和截图不纳入公开提交。该检查不等于运行时语义验证。

覆盖重复赋值、同一行多个调用、分支合并、循环、Data/Metadata 重复记录、参数覆盖、未知函数、伪调用/注释、格式错误、显示截断、坐标结构缺失、分页、预算、模型切换和导出隔离。

## 6. 兼容、数据安全与性能

只分析选中 TI，不扫描整张图，不执行 TI、不连接服务器、不更新源库。源码上限 250,000 字符、单语句上限 1,000 token、节点上限 5,000；调用/观察记录上限 2,000，达到预算明确给出诊断。页面还限制定义、读取、坐标及调用展示数量并说明截断，预算内完整材料可导出。

词法位置使用扫描过程的行起点，避免反复扫描前缀。对象目录查询不加载维度元素全集。原学习/解析接口采用可选扩展，旧默认行为和已有页面保留。

## 7. UNKNOWN 与限制

这是静态语法定义检查，`runtime_verified=False`。不求值、不证明执行次序、零分母行为、精度、目标原值、别名、成员存在性、Rule/Feeder 或数值贡献。

标识符和运算支持有限；未知函数、循环与重复记录传播、分支不一致、损坏语法均保守处理。If 条件仅标记路径未求值并保留源位置；不重建完整谓词。字符串值隐藏，不能用本材料替代原源码。列位置按 Unicode 字符计数。

子过程参数传播和展开尚未接入；跨过程工作流、人工确认业务模式、可独立运行模块与迁移测试包仍待后续纵向交付。

## 8. 下一项纵向闭环

在限定入口与单个子 TI 范围内，连接显式参数绑定 → 被调用方使用位置 → 读写坐标，保留动态名称和控制路径 UNKNOWN。随后让用户对有证据的计算片段补充业务问题、适用条件、反例与验证样例，再保存为可复用经验；不靠通用文字替代计算事实。
