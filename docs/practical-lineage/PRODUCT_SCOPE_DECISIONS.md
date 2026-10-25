# 实用性回归：范围与差距评审

日期：2026-10-24。该页记录 Phase 0/1 初始范围；Phase 2/3 续作见下文，Phase 4 未实施。

## 用户问题与产品支柱
用户需要快速回答 Cube 的上下游、处理机制和独立切面。对应 Lineage & Relationships 与 Architecture Explorer。纯查看不能污染用户设计资产或触发保存提示。

## 针对性源码审计
|能力|现有实现 / 证据|差距与处置|
|---|---|---|
|浏览保存状态|`architecture-workbench.js` 的 changed、remember、beforeunload；查询、选中、拖动均调用 changed|根因是浏览和持久编辑共用 dirty。加入页面只读产品开关，浏览不写工作区、不设置 dirty、不恢复临时会话、不检查草稿过期|
|设计与草稿|`workbench.py` Workspace v3、`design.py`、workbench 设计接口|保留数据和实现；入口隐藏/禁用，连接手柄禁用；历史草稿不投影到只读模型图|
|Cube 关系|`workbench.py` indexed_graph/query_graph|已有 Cube→TI 读、TI→Cube 写、Cube→Cube 候选投影；直接复用，不新写图算法|
|Rule 引用|`workbench_rules.py` 复用 Rule IR 与 Unified Relations|仅已确认 Cube 身份的引用公开；Rule 与 Feeder 分开。复用原核对流程|
|写入与切面|`store/calculation.py` inspect、_coordinate_bindings；`store/data_row.py`|已有独立写入、坐标目录验证、条件与变量链。旧 writes API 缺少每写入的 read_nodes 和读取坐标，补充只读字段|
|页面入口|`app.py` /graph、_cube_detail.html|Cube 详情早已有 /graph?cube 链接，但路由未接受 cube 参数，落到 TI 页面。补齐处理并保留 ti 链接|
|展示|既有 canvas、Inspector、Mermaid viewer|增加轻量关系表 presenter；默认表格，简图按需。没有新解释器或架构引擎|

## 本轮决策
- 架构只读；工作区持久编辑暂不开放。历史备注、MDX 可只读查看，MDX 不执行。
- Cube 血缘默认直接关系，一对 Cube 的 TI 聚合仅为展示；不同写入点不合并算法。
- 候选共同读写不升级为值流；静态表达式读取依赖只在具体写入详情中说明。
- 源切面未知时保留未知；不从 vValue 名称、维度位置或对象名称推断来源。
- 不全面改造 TI 页面、导航、代码生成或分析核心。

## 风险及验收
界面可能隐藏历史设计资产，但绝不删除。用合成历史工作区恢复和哈希比较验证。验证十对象浏览、布局、拖动、退出零弹窗与零保存请求；验证多 TI、多源、多写入、Rule、自环、动态对象和无证据负例。

## 后续续作
用户在 Phase 0/1 交付后要求“继续”，本轮增量实施 Phase 2 的 TI 调用表与有限三层报告。详细范围见 TI_CALL_GRAPH_SPEC.md、RECONSTRUCTION_REPORT_SPEC.md；Phase 3/4 未实施。

## Phase 3 续作
后续“继续”交付只读模块概览和共享图表阅读适配，见 PHASE_3_READABILITY_REPORT.md。只调整展示层，不改变既有计算事实；Phase 4 未启动。
