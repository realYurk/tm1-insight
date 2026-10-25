# Cube 血缘核对

## 保留的语义

默认仍是 Cube→Cube 关系表，TI 是处理机制。共同读写是 TI_CANDIDATE；Rule 是声明式引用；Feeder 不混入普通值流。核对完成不改变关系级候选状态。只有已有定义链支持的写入点展示静态读取依赖，且 runtime_verified 始终为 false。

## 本轮改善

- 每个关系保存各 TI 的独立写入记录，保留操作、条件、表达式、源码位置和坐标；不按同一目标粗暴合并。
- 表格回填全部已核对记录的数量与写入方式，展示前三个写入摘要，其余进入详情。
- VIEW 值列只在现有绑定状态为 STATIC_CELL_VALUE_DEPENDENCY 且 source_cube 匹配时展示；数据源声明本身不会供应源切面。
- 新增摘要导出和有限研究报告，预算 1～20，默认 8；缓存同一 TI/Rule 的当前查询响应，跨关系复用请求，分别保留关系证据。
- 取消、部分失败、模型变化、预算截断和覆盖度明确记录；失败对象不计为完成。

## 合成证据案例

ViewLoad 的 Data：`n=vValue*2; IF(vYear @= 'Member1'); CellIncrementN(n,'Cube_B',vYear,vProduct,'Member2'); ENDIF; CellIncrementN(42,'Cube_B',vYear,vProduct,'Member1');`

已有 NativeView 元数据确认 Cube_A / Input；变量 vYear、vProduct 对应 Year、Product，vValue 对应值列。第一写入 `data:1:35` 保留 vValue→n 的静态计算链，目标 Year=vYear、Region=vProduct、Measure=Member2。第二写入 `data:1:93` 的常量 42 不产生 Cube_A 值依赖。Region 与 Product 只是目标/源各自的坐标，不推断维度同名或运行时成员映射。

Multiple 同时读取 Cube_A 和 Journal，但只有 Cube_A 读取参与首个写入值。Journal→Cube_B 始终没有已证明的值流；第二个未知变量写入仍为未知。Self 自环、RuleOutput 的 Rule 引用保留独立类型。

## 浏览器结果

独立 localhost:8809 合成模型有 4 条 Cube_B 关系、10 个关系内 TI/Rule 核对项、9 个唯一请求对象。预算 1 请求复用后完整 1、部分 1、未核对 2；预算 20 从空缓存开始完成 9 次请求，完整 4、部分 0、未核对 0。这里的完整指查询范围内核对完成，不代表模型全量或运行时语义完整。

默认图预算仍为 40 Cube / 100 关系；Rule 图投影仍有既有预算。预算之外不会静默扫描。页面关闭结束队列；核对状态不自动持久化，需下载报告保存。
