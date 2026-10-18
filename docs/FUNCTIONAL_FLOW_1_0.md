# Functional Flow 1.0 — 业务流程图

## 用户工作流

从 Cube 或 TI 详情点击 **业务流程图**，或在系统架构工作台切换到同名视图。
也可打开 `/architecture?kind=discover&view=functional_flow`，输入对象名或前缀，
选择一个本地 Cube / TI 作为入口。前缀用于发现候选，不会把同名对象自动拼成业务链。
选定入口后沿已有引擎的真实关系展开，不以名称前缀截断依赖。

默认图按「来源 → 处理 / 规则 → 结果 / 中间数据」布置。此布置用于阅读，
不是执行先后。点击节点查看维度、上下游及切面；点击连线查看动作与依据。
长 TI 名在图内保留头尾，完整名称保留在悬停提示、详情和导出中。
从 TI 详情卡可进一步以该 TI 为入口，缩小复杂模型的观察范围。

默认只展示入口的核心读写与目标 Rule；调用入口、下游消费者及来源 Cube 的
其他 Rule 可通过开关展开。技术辅助、控制 / 坐标查找关系及未确认目标留在证据层。
技术角色复用现有 Unified Relations 和 Cube Profile，不按业务名称猜测效果。
辅助程序内已经确认的核心读写效果仍保留在所属步骤中。

## 可复用能力与设计边界

`functional_flow.py` 是现有 Architecture 的展示投影，不调用新 Parser、图遍历、
计算引擎或 AI。输入来自现有索引的：

- `relation_objects`、`unified_relations`、`relation_evidence`；
- Cube Profile、`business_steps`、`rule_summaries`；
- 写入说明中的坐标与条件；不加载完整 TI 源码或 Rule AST。

代码证据、规则表达式、条件与定义链沿用现有 `relation-context` / `evidence` 接口按需加载。
所有分析连接只读。无采集、服务器调用、单元格读取或正式数据库迁移。
任务创建、进度、取消、来源变化检测继续使用已有 Architecture task 链路。

## `functional-flow-1` 数据契约

顶层包含 `schema`、`entry`、`model_fingerprint`、`runtime_verified=false`、
`include_context`、`nodes`、`edges`、`evidence`、`statistics`、`limitations`。
`context_document=Architecture.json` 指明语句 / 写入点引用的伴随文件。

节点保留稳定身份、类型、原始名称、展示标题、观察角色、作用摘要、上下游、
维度列表、切面摘录、原始对象 ID 及上下文引用。Cube 的角色仅描述局部读写事实；
TI 类型按实际访问和调用行为描述，不凭名称声称“分摊”等业务用途。

连线保留稳定身份、方向、可读动作、底层关系 ID、证据 ID、上下文、切面和缺口。
读操作方向为 Cube → TI，写操作为 TI → Cube，调用为 Caller → Callee，
调度为 Chore → TI，Rule 引用为 Cube → Rule 组，Rule 目标为 Rule 组 → 所属 Cube。
不同动作不会合并。写入访问与逐写入点仅在展示层归为一个动作，独立证据仍然保留。
同一 Cube 的多个 Rule 仅为展示归组；不将多个 DB 调用合并为一个直引公式。
Feeder 不进入数值计算图，原有独立语义保持不变。

切面每组最多六个已记录维度，目录确认的固定成员优先。简单标识符显示为变量，
查找或复杂表达式显示待确认；缺失维度归属时不靠位置补齐。相同摘录可归组，
`write_sites` 与 `context_refs` 保留原写入点，不声称其余维度相同。

共同读写候选和已证明的值依赖都不会转换成新的 Cube → Cube 传输箭头。
用户看到的是独立访问动作，不代表逐行映射、数值贡献、运行验证或迁移等价。
动态目标不生成确定节点；对已知 Cube 的引用仍可展示，未确认坐标留在关系证据中。

## API 与导出

复用现有工作台与任务：

```text
GET /architecture?kind=cube&name=Cube_B&analyze=1&view=functional_flow
GET /api/architecture/tasks/{task}/functional-flow
GET /api/architecture/tasks/{task}/functional-flow?include_context=true
GET /api/architecture/tasks/{task}/export?format=flow-markdown
GET /api/architecture/tasks/{task}/export?format=mermaid
GET /api/architecture/tasks/{task}/export?format=flow-json
```

三个导出均接受 `include_context`，与主图开关一致；原有 JSON、Markdown、ZIP、
Evidence 和 Unified Relations 导出不变。Markdown 提供流程图、对象、动作与切面，
证据附后折叠；Mermaid 提供可直接画图的文字；JSON 保留分层引用与确认边界。
完整源码和 IR 不复制到每条边。需要完整语句时请配套保留 Architecture.json。
导出包含本地对象名称及切面，应由用户自行决定分享范围。

## 资源与兼容性

默认显示最多 48 节点 / 160 动作；API 最大 100 / 300。达到预算会明确提示图不完整。
投影仅读取局部任务的已有只读 SQLite 索引，关系 / 对象读取有界；坐标摘录最多
读取 2,000 个写入点。不为展示重复解析 Rule、不读取所有 TI 正文、不迁移旧快照，
不改变 Architecture 语义修订号。旧报告没有新增关系时返回空图，不制造替代关系。

前端无外部字体、CDN、图形库或网络依赖。节点使用 DOM 文本，连线使用本地 SVG。
长名、引号、换行和 Markdown / Mermaid 特殊字符按输出场景转义。
异步视图切换和上下文开关阻止过期响应覆盖当前结果。

## 验证与限制

`tests/test_functional_flow.py` 覆盖方向、证据、共同读写反例、技术效果折叠、
切面保守性、独立写入点与条件、Rule / Feeder 分离、动态未知、循环、确定性、
预算、上下文开关、旧数据兼容、三种导出、入口与静态资源。合成用例不含企业源码。
真实本地模型验收、截图、性能记录和导出留在私有验收目录，不随源码发布。

这不是运行时流程图，也不会自动给出人工未确认的业务解释。复杂大图需要缩小入口，
三列布局不是拓扑排序；局部没有调度定义不证明服务器没有调度。Data 行变量的
来源证据不会因新增展示层而变得完整。下一步优先根据实际使用反馈改进聚焦与布局，
继续保留这一事实 / 展示边界。
