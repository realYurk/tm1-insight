# Cube 血缘 v1：已实现契约

## 入口与范围
- `/graph` 或 `/graph?cube=名称`：Cube 主体关系表。
- `/graph?ti=名称` 和 `/graph?ti=`：保留原 TI 页面。
- Cube 原详情链接直接生效；只读架构 Cube Inspector 增加“查看 Cube 上下游与切面”。
- 复用 `POST /api/workbench/graph`，view=cubes、depth=1、node_budget=40、edge_budget=100、类型 TI_CANDIDATE / RULE_REFERENCE。
- 原 graph API 兼容，规则预算仍为最多 12 个所属 Cube / 每文件 256k 字符。预算与缺失入口明确显示。

## 关系表和图
来源 Cube、目标 Cube、机制、源/目标切面摘要、证据状态、详情。TI 名称为机制；Rule 独立一行。多个 TI 可聚合到同一候选关系，逐 TI、逐写入点核对。汇总行只摘要最近主动核对 TI 的第一个写入，明确总写入数，不能代表所有写入。

简图由同一批表格关系生成，Cube 节点，候选关系虚线，Rule 引用实线。最多 24 Cube / 30 关系，超过时保留表格并解释。自环保留。不添加伪造顺序。

## writes API 增量字段
原字段保留，新增：
- `writes[].read_nodes`：现有 Calculation 中该写入值表达式的读取节点 ID。
- `writes[].control_context`：现有分支/循环上下文，未求值。
- `reads[]`：id、cube、operation、resolution、coordinate_mapping、evidence。
- `read_total`、`read_scope=CALCULATION_RETAINED_NODES_NOT_ALL_PROCESS_READS`。

最多展示 80 写入 / 160 保留读取。Calculation 会裁剪无贡献表达式，reads 不是 TI 全部读取清单。UI 不把未保留读取解释为不存在。源切面仅来自本写入 read_nodes 中且 Cube 身份匹配的读取节点；其他读取只能作为独立观察。源 View / Subset 的完整范围本轮未补充，未知不推断。

## 坐标与证据
TI 坐标依赖现有 Cube 维度顺序和参数个数核对；固定成员只有现有绑定器验证维度成员目录后才显示固定。运行时参数、Data Row、Lookup 与未解析表达式分开。每个写入保留 section/line/column、value_expression、条件、定义链、未确认原因和源码链接。
Rule 保留原 RHS、LHS、DB 参数、源码位置和完整 IR 详情。DB 参数顺序不冒充维度映射，裸 LHS 成员无归属元数据时维度保持待确认。Feeder 不作为数值来源；默认不加入 Cube 数值关联主表。

## 导出
“导出当前报告”包含当前关系表与本次主动核对的证据附录，schema=`cube-lineage-review-1`，含 snapshot_id/query/limits/relations/inspected。未主动核对的位置不冒充完整模型报告。已有架构导出接口不变。该轻量导出还不是 Phase 2 的三层重构报告。
