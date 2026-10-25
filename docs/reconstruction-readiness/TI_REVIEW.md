# TI 调用与重构报告

## 复用及修复

继续使用 workflow 的调用遍历、条件、命名参数、Caller 索引、Chore 定义与 calculation/data_row 的逐写入解释。没有修改计算解析器。

新增 source_declaration 适配器只读取指定 Process。四 Section 总长度超过 250000 字符时不加载正文；元数据 payload 超过 200000 字符时不读取。先复用现有源码数据源解析，必要时消费哈希匹配、无动态覆盖的采集声明。只输出必要 Cube/View/类型与证据，不输出连接字符串、文件路径或 SQL。

数据源声明与已有 NativeView 变量绑定独立呈现。旧快照缺 Variables 或元数据表仍可打开；可确认声明不丢失，但绝不由变量名补造值来源。write_fields 增加 data_row_value_dependencies，保留已有 binding 状态与值链。

## 三层报告

1. 通俗摘要：基于源码操作说明声明来源、显式 CellGet、目标和覆盖/累加、直接调用观察。不根据 TI 名称推断分摊等算法。
2. 工程明细：Caller 索引、直接调用、下游调用的真实端点、调度定义、命名参数、条件、逐写入坐标及值表达式。下游读写不混入入口摘要。
3. 证据附录：Section、源码位置/哈希、分析版本/预算、循环、数据源变量及未解析因素。JSON 保留原结构并新增字段；Markdown 可独立阅读。

## 已验收案例

- ViewLoad 没有 CellGet，summary.reads 仍为空，summary.view_sources 为 Cube_A；页面说明使用 Cube_A 的 Input View 作为声明数据源并对 Cube_B 累加。vValue 值列依赖只属于第一写入，常量第二写入不关联源值。
- MissingVariables 保留声明但不建立值依赖；MDXView/未知布局保留未知。动态源码覆盖或陈旧元数据不能成为有效 View 来源。
- Caller→Load 的 vYear 命名绑定和 IF 条件分别展示；动态 ExecuteProcess 没有具体 callee。Load→BusinessChild、BusinessChild→Load 保留真实端点及循环边界，不编造执行顺序。
- Nightly→Caller 为已记录调度步骤 0；启用状态未采集，不声称实际运行。

这些都是合成数据验收，不冒充真实 BP 模型结果。未执行 TI、MDX 或业务单元格请求。
