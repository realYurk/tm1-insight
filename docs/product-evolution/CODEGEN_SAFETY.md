# CODEGEN_SAFETY — 生成器可信度

> 代码：`src/tm1_insight/codegen_safety.py`、`store/codegen.py`、`design.py`
> 测试：`tests/test_codegen_safety.py`（32 项）

## 1. 表达式：安全子集，而不是"原样输出"

`validate_expression()` 只接受：

| 允许 | 说明 |
|---|---|
| 字符串字面量 | `'2026'`，内部 `''` 转义 |
| 数字 | `-?\d+(\.\d+)?` |
| 变量 | `vXxx`（生成侧变量） |
| 白名单函数 | `TimSt`、`NumberToStringEx`、`SUBST`、`UPPER`、`LOWER`、`TRIM`、`StringToNumberEx`、`NumberToString`，**必须带括号** |
| 白名单常量 | `Now` |
| 拼接 | `|` |

拒绝（返回具体原因）：

- 换行、分号、`#` 注释 → 会被拼接成额外语句；
- 赋值 / 比较（`=`、`@=`）；
- 非白名单标识符或函数（`ProcessQuit`、`ItemSkip`、自定义过程）；
- 括号不匹配、表达式不完整；
- 任何未识别字符。

**未通过校验的映射不会进入生成**：预检返回 `UNSAFE_EXPRESSION` 并阻断，不产出代码。
高级自定义 TI 语句本轮**不支持**——需要走人工编写，不伪装成"已验证"。

## 2. 成员与变量

| 风险 | 处理 | 位置 |
|---|---|---|
| 成员含单引号 | `O'Brien` → `'O''Brien'` | `quote_member` |
| 成员含换行/控制字符 | 拒绝（`ExpressionError` / `FIXED_MEMBER_UNSAFE`） | `quote_member`、预检 |
| 维度名含空格/Unicode | 规范化为 `vCamelCase`，**不改业务名** | `normalize_var` |
| 两个维度规范化后同名 | 生成侧加 `_2` 后缀并记录 `collisions` | `build_var_map` |
| 与保留字冲突 | 追加 `Value` | `RESERVED` 表 |
| 业务名与变量名映射 | 结果中同时保留 `variables` 与原始维度名 | `data_transfer` / `csv_to_cube` |

**不做静默改名**：业务对象名称始终保留在设计里，只有生成侧标识符被规范化。

## 3. 写入策略与清空策略分离

```python
write_policy: 'overwrite' | 'accumulate'   # CellPutN / CellIncrementN
clear_policy: 'target_scope' | 'none'      # 是否生成 ZeroOut
```

| 组合 | 生成结果 |
|---|---|
| overwrite + target_scope | 先 `}bedrock.cube.data.clear`，再 `CellPutN` |
| overwrite + none | 不生成删除语句，直接 `CellPutN` |
| accumulate + target_scope | 先清空，再 `CellIncrementN` |
| accumulate + none | 不删除，直接累加（重复运行会重复累计） |

- 非法策略在 `codegen` 层直接 `ValueError`，不会静默降级。
- UI 中两个下拉独立，并在选中 `none` 时提示"重复执行会重复写入"。
- 本轮**只实现两种**清空策略；`CLEAR_BATCH_SCOPE` 等更细粒度策略未实现，也未声称支持。

## 4. 依赖清单（Dependency Manifest）

`dependency_manifest()` 区分四类依赖：

| 类别 | 示例 | 缺失后果 |
|---|---|---|
| `TARGET_CUBE` | 目标 Cube | Process 无法写入 |
| `FRAMEWORK_CUBE` | `}APQ Settings`、日志 Cube、并行控制 | 日志与分隔符读取失败 |
| `FRAMEWORK_DIMENSION` | `}APQ Processes` | 日志维度插入失败 |
| `BEDROCK` | `}bedrock.cube.view.create`、`}bedrock.cube.data.clear` | 视图创建/清空失败 |

生成结果的 `dependencies` 会随 API 返回，UI 可展开查看，并明确写出"生成完成 ≠ 目标环境可独立运行"。

**本轮未实现**轻量（不依赖 `}APQ`）模板。现有模板保持原样，避免破坏已验收行为。

## 5. 生成前预检（Preflight）

`design.preflight()` 返回结构化问题 `{code, message, dimension?}`：

| code | 触发 |
|---|---|
| `TARGET_MISSING` / `TARGET_NOT_IN_SNAPSHOT` | 目标草稿不存在 / 真实 Cube 取不到维度 |
| `DIM_ORDER_EMPTY` | 目标没有维度顺序 |
| `SOURCE_MISSING` / `SOURCE_DIMS_MISSING` | 来源缺失 |
| `TEMPLATE_MISMATCH` | 模板与来源类型不匹配 |
| `VALUE_SOURCE_MISSING` / `VALUE_SOURCE_UNKNOWN` | 数值列缺失或不在 Schema |
| `DIM_UNMAPPED` / `DIM_UNCONFIRMED` | 未映射 / 未确认 |
| `FIXED_MEMBER_EMPTY` / `FIXED_MEMBER_UNSAFE` | 固定成员空 / 含控制字符 |
| `SOURCE_FIELD_EMPTY` / `SOURCE_FIELD_UNKNOWN` | 来源字段空 / 不在 Schema |
| `EXPRESSION_EMPTY` / `UNSAFE_EXPRESSION` | 表达式空 / 不在安全子集 |
| `LOOKUP_UNSUPPORTED` / `CONTEXT_UNSUPPORTED` | 当前模板不支持该坐标类型 |
| `EXTRA_DIM_MAPPING` | 映射维度不属于目标 |

任一命中 → `status=blocked, code=None`。**不存在"表面完整但缺映射"的输出。**

## 6. 生成记录与失效

- `summary.design_fingerprint`：只覆盖影响代码的字段（关系、目标草稿、来源草稿、Schema）。
- `summary.code_fingerprint`：四段代码正文的哈希（不含时间戳），同配置重复生成结果一致。
- `is_stale(artifact, design)`：设计变化（维度、字段、映射、策略、模板）后旧生成结果标记为失效。
- 项目实例保存 `code_fingerprint` 与 `verification_status`，重新生成时覆盖。

## 7. 静态校验覆盖了什么 / 没覆盖什么

**已覆盖（离线）**

- 四段齐全、参数个数与维度数一致、参数顺序与维度顺序一致；
- 固定成员/来源字段/表达式按配置写入；
- 覆盖/累加与清空策略的代码差异；
- 缺映射、未确认、非法表达式一律阻断；
- 变量名规范化与冲突记录；
- 依赖清单生成。

**未覆盖（需隔离环境人工验证）**

- TM1 语法与函数签名的最终正确性（如 `StringToNumberEx` 的区域设置差异）；
- `}APQ` / Bedrock 对象在目标环境是否存在；
- 大数据量下的性能与错误处理；
- `ItemReject` / 条件分支的运行行为；
- 清空范围对真实业务数据的实际影响。

## 8. 数值转换

`csv_to_cube` 当前固定生成：

```ti
vValue = StringToNumberEx( vQty, '.,' );
```

含义：小数分隔符 `.`、千位分隔符 `,`。

**限制**：未提供按列配置的区域格式；空串、非法字符、负号、大数、精度的实际行为取决于 TM1 运行时，本轮未做运行验证。需要在隔离环境用合成数据确认后再用于生产。
