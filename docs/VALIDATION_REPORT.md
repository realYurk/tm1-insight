# VALIDATION_REPORT — Architecture Workbench 1.0

> **命名说明**：仓库为公开仓库。本文档中的企业模型对象名已替换为等价合成占位名（如 `Sales Cost Driver`、`Planning PnL`），真实名称仅保存在本地未提交的验收记录中。
> 结论、数量、维度顺序、固定成员结构与行号均来自真实快照实测，替换仅涉及名称字面值。
> 环境：Windows 10 专业版 · Python 3.13.12 (`.venv`) · DuckDB 本地只读快照 · Chrome 真实内核
> 快照：本地只读 DuckDB（路径与快照指纹保存在本地验收记录，不写入公开仓库）
> 全程离线，未连接任何 TM1 Server。

---

# Round 2 — Visual Development 2.0（设计模式）

| 项 | 结果 |
|---|---|
| 全量 pytest | **948 collected / 948 passed / 0 failed / 0 skipped**（148s） |
| 新增专项 | `tests/test_visual_development.py` **25 项** |
| 设计模式浏览器验收 | `acceptance_design.py` **24 项全绿** |
| 工作台 1.0 回归 | `acceptance_workbench.py` 37 项全绿 |
| 真实鼠标验收 | `acceptance_pointer.py` 10 项全绿（单击 / Ctrl 多选 / 平移 / 点击边 / 框选） |
| 正式库 | 未修改（哈希与 Round 1 一致） |
| 生成代码 | 离线静态校验通过；**未在 TM1 执行** |

测试覆盖（`test_visual_development.py`）：

- Cube 草稿维度顺序保留、重复维度拒绝、空维度拒绝
- 草稿维度引用必须存在；草稿对象来源恒为 `DESIGN_DRAFT`
- CSV Schema 字段重复拒绝、来源标记、表头解析与类型建议（不读数据行）
- 映射未确认 / 固定成员为空 / 来源字段为空 阻断生成
- 缺失目标坐标、映射维度不属于目标 Cube、模板不匹配 阻断生成
- CSV 生成：维度顺序、固定成员、来源字段、`StringToNumberEx`、`CellPutN` 参数顺序
- 累加策略切换 `CellIncrementN`
- Cube → Cube 复用既有 `data_transfer`（`cCubSrc` 存在、固定成员正确）
- Cube 创建规格区分草稿维度与快照维度
- Blueprint 悬挂引用拒绝、版本保留
- 工作区设计态往返（Cube/维度/Schema/关系/映射）
- v1 工作区文件仍可加载
- API：meta / generate / blocked / cube-spec / 异快照 409
- `data_transfer` 新参数默认 `None`，旧调用兼容

生成代码静态校验项：

| 检查 | 方式 |
|---|---|
| 四段（prolog/metadata/data/epilog）齐全 | 断言字段非空 |
| 写入参数个数 = 维度数 | 断言 `CellPutN(vValue, cCubTgt, v1…vN)` 全串匹配 |
| 参数顺序 = 目标维度顺序 | 断言 `tgt_dims` 与语句一致 |
| 固定成员 / 来源字段正确 | 断言具体赋值行 |
| 缺失映射不生成 | 断言 `status=blocked` 且 `code=None` |
| 写入策略一致 | `overwrite→CellPutN` / `accumulate→CellIncrementN` |

浏览器验收（真实 Chrome，真实鼠标）：

1. 切设计模式 → 2. 建维度草稿 → 3. 建 Cube 草稿（5 维含草稿维度）→ 4. 画布出现草稿节点
5. 点节点看维度顺序 → 6. 粘贴表头建 Schema → 7. 建 CSV→Cube 关系
8. 配置 5 条映射 + 数值列 → 9. 生成并检查写入顺序/固定成员/转换
10. 保存 → 刷新 → 草稿/关系/映射恢复 → 11. 保存 Blueprint → 刷新恢复
12. 切回探索模式，真实对象搜索与详情仍可用

已知限制（设计模式）：

- 生成代码未在 TM1 编译或执行；`}APQ` 框架对象需目标环境已存在。
- 未实现一对多 / 聚合 / 分配映射；`LOOKUP`、`FROM_CONTEXT` 只保存意图。
- 未做 Cube 实际创建与部署。
- Blueprint 仅支持同 Snapshot 内保存与重开。

## 1. 单元 / 集成测试

命令：

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

| 指标 | 数值 |
|---|---|
| collected | **923** |
| passed | **923** |
| failed | 0 |
| skipped | 0 |
| 耗时 | 157 s |
| 与交接基线差异 | 896 → 923（新增工作台专项 26 + 本轮补充 1） |

工作台专项：

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_engineering_workbench.py -q
# 27 passed
```

覆盖：候选加工非值流、Rule/Feeder 方向与语义、前缀路径与不造假路径、深度/预算/自环、
稳定顺序与快照隔离、去重与技术对象过滤、关系过滤与缺失对象、未分类索引不外泄、
多 TI 聚合、前缀分页、有界血缘兼容旧接口、保存/恢复/幂等、并发修订拒绝、
写入失败保留旧文件、危险契约拒绝（7 组参数化）、非法路径与损坏文件、API 隔离与旧页面、
索引不读源码（SQL 追踪）、无凭据字段、边界不等于截断。

## 2. 浏览器验收（真实 Chrome）

| 脚本 | 断言项 | 结果 | 截图 |
|---|---|---|---|
| `acceptance_workbench.py` | 37 | 全部通过 | `30_workbench_initial.png` `31_workbench_act_writes.png` `32_workbench_restored.png` `33_codegen_roundtrip.png` |
| `browser_acceptance.py` | 8 步 | 全部通过 | `04_mermaid_view.png` `05_node_clicked.png` |
| `acceptance_pnl_formation.py` | 8 步 | 全部通过 | `20_pnl_formation.png` `21_pnl_mdx_slice.png` |
| `acceptance_allocation.py` | 6 步 | 全部通过 | `10_allocation_page.png` `11_allocation_result.png` |

工作台 37 项包含：

- 首屏渲染局部图（8 节点）、对象搜索、详情切换、图在详情打开后保留
- 展开直接 TI 关系（18 对象 / 24 关系）
- TI 详情显示读取/写入 Cube
- 写入切面：目标 Cube、**固定目标切面默认可见**、固定成员具体值、**运行时坐标默认可见**、`vValue` 原样、待确认项标注
- 源码区块展开并渲染 **454 行**带行号
- 创建人工模块、标注为人工解释
- 框选多选在图上高亮
- 保存工作区 → URL 带 `workspace_id`
- 刷新后自动恢复：名称、MDX 原文、MDX 结构、设计笔记、人工模块、图重渲染
- 点击图上边 → 关系表**唯一**对应记录被定位；边详情说明语义而非值流
- 两个 Cube 选中后出现模板入口 → 进入 `/codegen` 带入来源/目标 → 「返回原工作区」→ 仍是同一工作区
- 异快照请求返回 **409**
- 无页面脚本错误 / 控制台错误

## 3. 真实模型查询验收

对象：`Cub.Sales Cost Driver.Data.Load.From.Planning PnL.ACT`（真实存在）。

| 检查项 | 结果 |
|---|---|
| 读取 Cube | `Planning PnL`、`Product Master`、`Sys Planning Cube` |
| 写入 Cube | `Sales Cost Driver` |
| 调用方 | `…Planning Assumption.Caller`、`…Sales PnL.Export.To.Sales Cost Driver.Caller`、`…Planning Assumption.Caller` |
| 写入点总数 | 38（其中真实业务写入 **12** 个 `CellIncrementN`；26 个系统/未确认目标单独折叠） |
| 目标切面 | 14 维，按真实 Cube 维度顺序 |
| 固定成员 | `Sub Module = Planning Assumption`、`Step = Step 0`、`Rule Code = 0000`、`Driver Code = Driver Type 006…`、`M Driver = Amount` |
| 动态坐标 | `vScenario` `vVersion` `vYear` `vMonth` `vBusinessLine` `vPlantBase` `vBrand` `vCarLine` 及 `CellGetS(Product Master, …)` |
| 值表达式 | `vValue` 原样显示，`data_row_binding_status = NO_CONFIRMED_ROW_DEPENDENCY` |
| 未确认提示 | `MISSING_VARIABLE_METADATA: 旧快照未保存 Process Variables；请仅补采该 Process。` |

结论：**未把 `vValue` 推断为某个源字段，未把 `vBrand` 替换成固定品牌，未把候选共同读写当成值流。**

## 4. Rule / Feeder 分类验收

| Cube | 返回关系 | Rule 边 | Feeder 边 | `RULE_SOURCE_REFERENCE` 暴露 |
|---|---|---|---|---|
| `Planning PnL` | 61（TI_READ 50 / RULE_REFERENCE 10 / TI_WRITE 1） | `SOURCE_CONFIRMED`，行号真实 | 未请求时不返回 | **否** |
| `Sales Cost Driver` | 17（TI_WRITE 7 / RULE_REFERENCE 4 / TI_READ 6） | `SOURCE_CONFIRMED`，`semantic_status=PARSED` | 同上 | **否** |

`rule_scope` 诚实反馈：`Planning PnL` 为 `12/21 complete=false`，`Sales Cost Driver` 为 `4/4 complete=true`。

## 5. 性能

命令：`scripts/perf_workbench.py`（同一进程，索引进程级缓存）。

| 查询 | 模式 | 中位 ms | 节点 | 关系 | 截断 |
|---|---|---|---|---|---|
| 单 Cube `Sales Cost Driver` | 冷 | 141 | 43 | 48 | 否 |
| 单 Cube `Planning PnL` | 冷 | 161 | 60 | 67 | 是（达节点预算） |
| 前缀 `SC* → BP*` | 冷 | 210 | 39 | 40 | 是 |
| 前缀 `BP*` 下游 | 冷 | 172 | 60 | 71 | 是 |
| 手动 5 Cube | 冷 | 201 | 80 | 121 | 是（达节点预算） |
| 单 TI（ACT） | 冷 | 107 | 8 | 7 | 否 |
| 同上各项 | 热 | 154–192 | — | — | — |

索引构建：冷启动首查 **724 ms**（一次性，含 1500+ 对象与全部索引行），热态 **136 ms**。
每次请求只返回预算内子图，**不把整模型图传给浏览器**。

## 6. 数据保护

| 项 | 结果 |
|---|---|
| 连接真实 TM1 Server | 否 |
| 读取业务 Cell 数据 | 否 |
| 执行 TI / MDI / 真实 Rule | 否 |
| 修改正式 DuckDB | 否 |
| 修改 / 删除 WAL | 否 |
| 访问内网地址 | 否 |
| 外部 API / 遥测 | 否 |

正式库哈希（本轮开始与结束各测一次，**完全一致**）：

```
<采集库>  : 与测量前一致
<运行库>  : 与测量前一致
```

（具体哈希与路径属于内部标识，保存在不提交的本地验收记录中。）

工作区写入位置：`<repo>/workspaces/`（用户数据，已加入 `.gitignore`），与快照、DuckDB 分离。

## 7. 已知限制

| 类型 | 内容 |
|---|---|
| 一般 | 单次查询最多解析 12 个 Cube 的 Rule；超出时 `rule_scope_complete=false` |
| 一般 | 索引进程内构建，超大模型首次延迟与内存需按实测量级评估 |
| 一般 | 图中长对象名会截断显示，完整名在详情与关系表中 |
| 一般 | 「点击边」验收用事件派发而非像素命中（路径中心可能被节点覆盖），联动逻辑真实 |
| 远期 | 草稿 Cube 未与真实模板生成打通 |
| 远期 | 外部数据源仅展示声明，未做 Schema 映射 |
