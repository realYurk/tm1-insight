# ENGINEERING ASSET STUDIO — 工程资产工作台 3.0

> 入口：左侧导航「工程资产」→ `/assets`
> 代码：`src/tm1_insight/assets.py`、`src/tm1_insight/asset_package.py`、`api/assets.py`
> 测试：`tests/test_assets.py`、`tests/test_cross_project_reuse.py`

## 1. 它解决什么问题

2.0 能让用户**设计一次**；3.0 要能让用户**把这套设计带到下一个项目**。

四条链路：

```
设计工作区  --提炼-->  Blueprint（角色）  --绑定-->  新项目实例  --生成-->  TI 草案
     ↑                                                        │
     └──────────────── 保存为验证记录 / 资产包 ←───────────────┘
```

## 2. 资产类型

| 类型 | 内容 | 存储 |
|---|---|---|
| `Pattern` | 技术无关的设计模式：问题、输入、输出、步骤、适用/不适用 | `assets/patterns/*.json` |
| `Blueprint` | 可复用定义：角色、维度顺序、映射、模板、写入/清空策略 | `assets/blueprints/*.json` |
| `VerificationContract` | 验证要求清单（结构/映射/类型/依赖/幂等/清空/精度） | `assets/verifications/*.json` |
| `ProjectInstance` | 某项目中的绑定结果、生成指纹、验证状态、工作区链接 | `assets/projects/*.json` |

设计对象仍在工作区；资产库只保存**可复用描述**与**绑定结果**，不复制企业源码。

## 3. 从设计提炼 Blueprint

沙盘 → 设计模式 → 关系行「提炼为 Blueprint」。

生成的角色**完全按维度顺序**：

| 角色 | 类型 | 来源 |
|---|---|---|
| `target_cube` | cube | 目标 Cube 草稿名 |
| `dim_1..dim_n` | dimension | 目标维度顺序 |
| `member_i` | member | 该维度若为固定成员 |
| `field_i` | field | 该维度若来自源字段 |
| `expr_i` | value | 该维度若为表达式 |
| `value_field` | field | `vValue` 来源列 |
| `source_name` | value（可选） | 来源数据集名称 |

同时生成 `mappings`（维度角色 → 取值方式 + 来源角色），并记录 `write_policy` / `clear_policy` / `template`。

提炼时用户选择「是否标记为通用」：

- 通用 → `restricted=false`，可通过公开导出审查（仍需人工复核内容）；
- 否则 `restricted=true`，公开导出会被**阻断**。

## 4. 在另一个项目中使用

资产页 → 选择 Blueprint → 逐角色填写绑定值 →「在新项目中使用」。

- 每个角色都有输入框与「已确认」勾选；
- 绑定值必须非空（必需角色），维度名不能重复，表达式角色走安全子集校验；
- 通过后生成一份新的 `Design`（Cube 草稿 + Schema + 关系 + 映射），并**同时**：
  1. 保存为 `ProjectInstance`；
  2. 写入一个新的用户工作区，页面提供「在架构沙盘中打开」。

生成不修改任何真实对象；项目实例状态从 `BOUND` → `GENERATED`。

## 5. 项目详情与验证状态

验证状态分级（不使用单一布尔值）：

| 状态 | 含义 |
|---|---|
| `DESIGN_VALIDATED` | 设计结构通过静态校验 |
| `CODE_GENERATED` | 已生成代码 |
| `CODE_STATIC_CHECKED` | 生成代码通过当前静态检查（当前最高可自动达到） |
| `SYNTHETIC_TESTED` | 通过合成测试（需人工登记测试范围） |
| `RUNTIME_VERIFIED` | 在隔离 TM1 环境真实执行（本轮**不可达**） |

项目详情显示：Blueprint 版本、绑定、生成指纹、验证状态、工作区链接、生成/阻断结果。

## 6. 资产页交互

- 左侧：类型筛选（Blueprint / Pattern / 验证契约 / 项目）+ 搜索 + 列表；
- 右侧：详情。Blueprint 详情优先展示「解决什么 / 需要什么输入 / 角色绑定 / 模板 / 风险」，JSON 退居细节；
- 顶部：新建 Pattern、导出范围（私有/对外）、导出、导入。

## 7. 持久化与保护

| 项 | 实现 |
|---|---|
| 位置 | `<user_data_root>/assets/`（与快照、工作区分开） |
| 写入 | 临时文件 + `fsync` + `os.replace` |
| 并发 | 内容 sha256 作为 revision，不匹配则 `409` |
| 回滚 | 覆盖前保留 `<id>.json.bak` |
| 损坏 | 列表显示「不可读取（原文件保留）」，不删除 |
| 大小 | 单文件读取上限 512 KB |
| 路径 | 资产 id 必须匹配 `[a-zA-Z0-9_-]{1,80}` |
| 版本控制 | `assets/` 已加入 `.gitignore` |

## 8. 本轮未实现

- Blueprint 版本历史 / 差异比较（只有 `version` 字段）；
- 参数化角色（把 `Product` 直接写成 `{ProductDimension}` 占位符）；
- 跨 Snapshot 自动重绑（有意不做：同名不代表同语义）；
- 派生 Blueprint（基于已有 Blueprint 改局部）；
- 在资产页直接编辑 Blueprint 内容（当前只能新建、绑定、删除、导入）。
