# BLUEPRINT SCHEMA — 可复用设计成果

> 第一版目标：**同一个 Snapshot 内保存与重新打开**，并建立可版本化的数据结构。
> 不声称支持跨企业一键部署。

## 1. 工作区 Schema（`architecture-workspace-2`）

```json
{
  "schema_version": "architecture-workspace-2",
  "snapshot_id": "…",
  "name": "设计验收",
  "query": { … },
  "objects": [ … ],
  "design": {
    "mode": "design",
    "cubes": [ … ], "dimensions": [ … ], "schemas": [ … ],
    "relations": [ … ], "blueprints": [ … ]
  }
}
```

- v1 工作区文件仍可读取（`schema_version` 接受两个字面量），`design` 使用默认空值。
- 引用完整性在加载/保存时校验；失效引用直接拒绝保存，不会静默丢弃。

## 2. Blueprint 字段

| 字段 | 说明 |
|---|---|
| `id` | `bp-…`，唯一 |
| `name` / `note` | 用户命名与说明 |
| `version` | 从 1 开始，允许手动递增（1–1000） |
| `cube_ids` / `dimension_ids` / `schema_ids` / `relation_ids` | 引用的设计对象；必须全部存在 |
| `artifacts` | 生成物摘要：`relation_id`、`template`、`template_version`、`generated_at`、`status`、`validated`、`blockers`、`summary` |
| `created_at` / `updated_at` | ISO 时间 |
| `provenance` | 固定 `DESIGN_DRAFT` |

约束：

- 引用不存在的对象 → `422`；
- 对象 id 重复 → `422`；
- `artifacts.status` 只能是 `DESIGN_DRAFT`（结构上不允许写 `DEPLOYED`）。

## 3. 保存内容与安全边界

Blueprint **只保存设计描述**：

- 保存：名称、说明、维度顺序、字段清单、映射类型与固定成员、模板 id、生成摘要。
- 不保存：企业 Rule / TI 源码正文、连接信息、业务数据行。
- 生成代码仍在工作区关系上按需重新生成，不写入 Blueprint 正文。

## 4. 版本化与跨环境

- `version` 字段已就位，本轮不提供自动迁移或差异比较。
- 维度以**名称 + 角色**表达，但当前仍绑定具体名称；跨企业复用需要人工替换维度名与固定成员。
- 不宣称「跨 Snapshot 直接复用」：不同快照的同名对象不会被自动视为同一对象（身份含 snapshot）。

## 5. 未实现（明确记录）

| 能力 | 状态 |
|---|---|
| Blueprint 差异比较 / 版本历史 | 未实现 |
| 参数化角色（`Source Dataset`、`Target Cube` 等占位符） | 未实现 |
| 跨 Snapshot 自动重绑定 | 未实现（有意：避免错误映射） |
| Blueprint 导出为可分发资产包 | 未实现 |
| 部署状态回写（`DEPLOYED`） | 结构上禁止，避免误报 |

## 6. 使用方式

1. 完成一组设计（维度草稿 / Cube 草稿 / Schema / 关系 / 生成）。
2. 「⑥ Blueprint」填名称 →「保存为 Blueprint」。
3. 「保存工作区」。
4. 刷新或重新打开工作区 → Blueprint 与设计对象一并恢复。
5. 需要重新生成代码时，回到关系上重新执行（生成结果不随 Blueprint 冻结，避免过期代码被误当最新）。
