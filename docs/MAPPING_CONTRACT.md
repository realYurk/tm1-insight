# MAPPING CONTRACT — 设计关系与坐标映射

> 一份契约同时服务 CSV → Cube 与 Cube → Cube，避免两套映射编辑器。

## 1. 结构

```json
{
  "id": "rel-ab12cd34",
  "source": {"kind": "csv", "ref": "csv-xxxx"},
  "target": {"kind": "cube_draft", "ref": "draft-xxxx"},
  "mapping": [ { "target_dimension": "Scenario", "kind": "FIXED", "fixed_member": "Forecast", "confirmed": true } ],
  "value_source": "Quantity",
  "write_policy": "overwrite",
  "template": "csv-to-cube",
  "confirmed": true
}
```

- `source.kind`：`csv` / `cube_draft` / `cube`（`cube` 表示快照真实 Cube）
- `target.kind`：`cube_draft` / `cube`
- `value_source`：CSV 场景下提供数值的列名（Cube→Cube 由 `vValue` 承接）

## 2. 坐标类型

| `kind` | 语义 | 生成结果 | 当前是否可生成 |
|---|---|---|---|
| `FIXED` | 固定成员 | `vDim = '成员';` | 是 |
| `FROM_SOURCE` | 来自输入字段 / 源维度同名字段 | `vDim = vField;` | 是 |
| `EXPRESSION` | 用户给出的表达式 | `vDim = <表达式>;` | 是（按原样写入，需用户自证） |
| `LOOKUP` | 通过映射规则查成员 | — | **否**，保存为设计意图，生成时阻断 |
| `UNMAPPED` | 未映射 | — | 阻断 |

`FROM_CONTEXT`（执行上下文）当前没有模板支撑，UI 不提供该选项，避免产生无法生成的配置。

## 3. 校验（生成前，硬门槛）

任一条件成立即 `status=blocked`，**不返回任何代码**：

1. 目标维度没有任何映射，或 `kind=UNMAPPED`。
2. `FIXED` 但成员为空。
3. `FROM_SOURCE` / `LOOKUP` 但来源字段为空。
4. `EXPRESSION` 但表达式为空。
5. 映射未勾选「确认」。
6. 映射里出现不属于目标 Cube 的维度。
7. CSV 来源：未选择数值列，或数值列不在 Schema 字段中。
8. CSV 来源：`FROM_SOURCE` 指向的字段不在 Schema 中。
9. 模板与来源类型不匹配（CSV 必须 `csv-to-cube`，Cube 必须 `cube-data-transfer`）。
10. 目标 Cube 不在当前快照（且不是草稿），取不到维度顺序。

错误信息面向用户，直接说明缺哪个维度的什么内容。

## 4. 保存 vs 生成

- **保存宽松**：映射可以处于「未填完」状态并写入工作区，方便分次配置。
- **生成严格**：只有全部满足第 3 节才产出代码。
- 这样既不会丢用户中间进度，也不会静默生成空坐标。

## 5. 维度顺序

- 映射表**逐行对应目标 Cube 的维度顺序**（行号即位置）。
- 生成的写入语句参数顺序与之一致：`CellPutN(vValue, cCubTgt, v1, v2, … vN)`，N 必须等于维度数。
- 测试断言 `tgt_dims` 与写入语句参数一一对应。

## 6. 写入策略

| 值 | 生成 | 语义 |
|---|---|---|
| `overwrite` | `CellPutN` | 覆盖目标交叉点 |
| `accumulate` | `CellIncrementN` | 在目标上累加 |

目标清空（ZeroOut）由既有模板的 `}bedrock.cube.data.clear` 块承担，不在映射里另建逻辑。

## 7. 自动建议 ≠ 自动确认

- 当前版本**不做**按同名维度自动填充映射：所有条目默认 `UNMAPPED`，必须由用户选择类型并勾选确认。
- 原因：同名不代表相同业务粒度（例如 Car Line vs Car Model、Category vs SKU）。
- 一对多 / 多对一 / 聚合 / 分配规则本轮不支持；需要时保持未映射，生成会被阻断，而不是产出错误代码。

## 8. UI

右侧面板内逐维度渲染一行：

```
1. Product   [固定成员 ▾] [输入值/字段]  ☑ 确认
```

- 类型切换会重置输入提示；
- 「全部标记为已确认」仅在类型与值都填好后使用才会通过校验；
- 数值来源列（CSV）与写入策略在选择后立即写回设计关系，随工作区保存。
