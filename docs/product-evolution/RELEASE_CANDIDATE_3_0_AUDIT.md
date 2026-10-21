# Release Candidate 3.0 审查报告

> 审查对象：`codex/engineering-asset-3`（起点 `3860dce`，审查前 HEAD `b609bae`）
> 审查日期：2026-10-21
> 结论：**发现 2 项 BLOCKER、4 项 HIGH、3 项 MEDIUM，全部修复并补测试；master 未改动、未合并。**

本报告只记录真实代码与真实运行结果。所有「已验证」均注明验证方式；未在 TM1 环境执行的一律标注为未验证。

---

## A. 仓库证据

| 项 | 值 |
|---|---|
| 分支 | `codex/engineering-asset-3` |
| 审查前 HEAD | `b609bae` |
| 修复后 HEAD | `82a6057`（随后追加本报告提交） |
| 起点 | `3860dce`（`codex/visual-development-02`） |
| `origin/master` | `8ef6d67`（**未改动**） |
| 工作区 | 仅剩用户本人的需求说明书（未跟踪，未改动） |
| 强推 / 历史改写 / 删远程分支 | 无 |

本轮修复提交：

| SHA | 内容 |
|---|---|
| `a15ae24` | 生成器：清空范围、变量解析、名称注入 |
| `24c7eea` | 资产与资产包：解压上限、全类型审查、删除保护 |
| `163d2f1` | UI：清空范围、数据源变量、过期状态 |
| `82a6057` | 攻击性测试 88 项 + 设计验收扩充 |

修改范围：`codegen_safety.py`、`store/codegen.py`、`design.py`、`assets.py`、`asset_package.py`、`api/assets.py`、`api/workbench.py`、`architecture-workbench.{js,css}`、`assets.js`、两个模板、新增 `tests/test_rc_attack.py`。

---

## B. 代码审查发现

### BLOCKER

#### B-1 设计生成的 TI 会清空整个目标 Cube

| 项 | 内容 |
|---|---|
| 文件 | `src/tm1_insight/design.py` → `cg.data_transfer(...)` / `cg.csv_to_cube(...)` |
| 问题 | 生成时从未传 `tgt_filters`，而 `clear_policy` 默认 `target_scope`，`_zero_out` 收到空筛选即生成 `sFilter = '';`。Bedrock `}bedrock.cube.data.clear` 在 `pFilter` 为空时的语义是**清空整个 Cube**，不是清空切片。 |
| 复现 | 建两个 Cube 草稿 + 全 FIXED 映射（Scenario=Forecast、Year=2026），生成后 `prolog` 含 `}bedrock.cube.data.clear` 且 `sFilter = '';` |
| 风险 | 用户以为只刷一个切片，部署后执行会把该 Cube 全部 Scenario/Version 的真实数据删掉。 |
| 修复 | ① 由**已确认**的 `FIXED` 映射派生筛选条件；② 派生不出任何条件 → `CLEAR_SCOPE_UNDEFINED` 阻断，不给代码；③ `_clear_plan` 在模板层如实返回 `clear_scope`，`UNSCOPED_WHOLE_CUBE` 时 `generate` 二次拦截；④ UI 显示「清空范围：Scenario = Forecast；Year = 2026」。 |
| 测试 | `test_unscoped_clear_is_blocked_for_design`、`test_unconfirmed_fixed_member_cannot_define_clear_scope`、`test_clear_scope_is_derived_from_confirmed_fixed_members`、`test_codegen_direct_call_reports_unscoped_scope`、`test_api_generate_blocks_unscoped_clear` |
| 状态 | 已修复 |

#### B-2 生成的 `vDim` 赋值指向不存在的变量

| 项 | 内容 |
|---|---|
| 文件 | `design.py::MappingEntry.as_codegen_spec` vs `codegen_safety.build_var_map` |
| 问题 | 两套变量命名逻辑并存：`as_codegen_spec` 用它自己的 `re.sub` 拼 `vXxx`，与 Data Source 变量表（`build_var_map`）不一致。 |
| 复现 | 列 `unit_cost`：Data Source 变量是 `vUnitCost`，生成代码却是 `vMeasure = vUnit_cost;`。重名列（`A B` 与 `A-B`）时还会漏掉 `_2` 后缀，两个维度读到同一变量。 |
| 风险 | TI 引用未定义变量 → 运行报错；或两个维度被赋成同值 → **静默写错数据**。 |
| 修复 | `as_codegen_spec` 只声明 `source_field`，变量名统一由 `build_var_map` 解析；未命中字段进入 `unresolved` 并阻断生成。 |
| 测试 | `test_snake_case_field_matches_datasource_variable`、`test_variable_collision_uses_suffixed_name_consistently`、`test_unresolved_source_field_blocks_generation` |
| 状态 | 已修复 |

### HIGH

#### B-3 对象名直拼语句，可注入 TI 代码

| 项 | 内容 |
|---|---|
| 文件 | `store/codegen.py`（`_declare_constants`、`csv_to_cube` 的 `cSrcFile`、`_build_filter`、`_header_block`、Data 段注释） |
| 问题 | `cCubTgt = '{tgt_cube}';`、`cSrcFile = '{file_path}';`、`'pFilter'` 的维度名/成员名、注释里的维度名全部原样拼接。 |
| 复现 | Cube 名 `Tgt';ProcessQuit;'` → `cCubTgt = 'Tgt';ProcessQuit;'';`（可执行）。维度名含换行 → 注释被截断，下一行成为语句。 |
| 风险 | 任意 TI 语句注入（`ProcessQuit`、`CellPutN`、`ExecuteProcess`）。 |
| 修复 | ① 统一 `quote_member` 转义（`'` → `''`）；② 注释统一 `comment_text`（换行/控制字符转空格）；③ 名称含换行/控制字符在预检与模板层双重拒绝（`UNSAFE_NAME` / `ValueError`）。 |
| 测试 | `test_unsafe_cube_name_is_rejected`（3 种）、`test_quoted_cube_name_is_escaped_not_blocked`、`test_newline_in_schema_name_is_rejected`、`test_quoted_schema_name_is_escaped`、`test_codegen_refuses_unsafe_names_directly`、`test_member_with_quote_is_escaped_not_injected`、`test_filter_member_with_quote_is_escaped` |
| 状态 | 已修复（单引号保留为合法名称字符，靠转义而非拒绝） |

#### B-4 四段代码不含 Variables 定义，却没有任何提示

| 项 | 内容 |
|---|---|
| 问题 | 生成只输出 prolog/metadata/data/epilog。字符分隔源的 `vSKU`/`vQty` 必须在 Process 的 **Variables 页签**按列顺序创建，此前只以注释形式出现在 prolog 里，UI 完全不提。 |
| 风险 | 用户「复制粘贴即可运行」的预期落空；变量缺失时运行报错或读到空值。 |
| 修复 | 生成结果新增 `process_config.data_source_variables`（序号、变量名、来源列、类型）与 `datasource`（文件、分隔符、引号、编码、表头行）；UI 以「数据源变量（需在 Process 的 Variables 页签按顺序创建）」列出，并说明四段代码不含 Variables 定义。 |
| 测试 | `test_api_generate_exposes_clear_scope_and_variables`、`test_snake_case_field_matches_datasource_variable`；浏览器 `acceptance_design.py` 「生成面板列出数据源变量」 |
| 状态 | 已修复 |

#### B-5 资产包「对外导出」只审 Blueprint

| 项 | 内容 |
|---|---|
| 文件 | `asset_package.py::export_preflight` |
| 问题 | 只对 `blueprints` 调用 `scan_blueprint`；`patterns`、`verifications` 完全未扫描。 |
| 复现 | Pattern 的 `summary` 写 `参考 D:/corp/model/secret.xlsx` → `scope=public` 仍返回 `ok=True`。 |
| 风险 | 绝对路径/疑似凭据随「可公开」包外流。 |
| 修复 | 抽出 `scan_model(kind, obj)`，三类资产共用同一套规则；`public` 下只要出现 BLOCKER 即拒绝。 |
| 测试 | `test_export_public_blocks_sensitive_marker_in_pattern`、`test_export_public_blocks_credential_in_verification`、`test_export_public_blocks_restricted_blueprint`、`test_private_export_allows_restricted_with_blockers_reported` |
| 状态 | 已修复 |

#### B-6 导入无解压上限（zip bomb / 资源耗尽）

| 项 | 内容 |
|---|---|
| 文件 | `asset_package.py::import_package` |
| 问题 | 只限制压缩包字节数；`zf.read()` 会一次性解压。伪造 `file_size` 或高压缩比条目可耗尽内存/磁盘。 |
| 复现 | 一个 12 KB 的 zip 内含 20 MB 全零条目 → 旧实现直接解压。 |
| 修复 | 条目数 ≤ 500、解压总量 ≤ 20 MB、单文件 ≤ 2 MB；读取改用 `_read_capped`（有界句柄，读 `limit+1` 即停）；反斜杠路径与盘符一并拒绝。 |
| 测试 | `test_import_rejects_too_many_entries`、`test_import_rejects_decompression_bomb`、`test_import_rejects_path_traversal`（5 种路径）、`test_import_rejects_disallowed_directory` |
| 状态 | 已修复 |

### MEDIUM

| 编号 | 问题 | 修复 | 测试 |
|---|---|---|---|
| B-7 | 删除 Blueprint 不检查项目引用，历史项目变成悬挂引用 | 删除前扫描项目；被引用返回 409 并列出项目，需 `force=true` | `test_delete_guard_reports_referencing_projects` |
| B-8 | 同一角色重复绑定被 dict 静默合并（后者胜出） | `validate_bindings` 显式报「角色被重复绑定」 | `test_duplicate_role_binding_is_rejected` |
| B-9 | Cube 源的 `FROM_SOURCE` 字段未校验是否存在于源维度，只在校验为 CSV 时检查 | 用源维度集合统一校验 | `test_cube_source_field_must_exist_in_source_dims` |
| B-10 | 表达式把 `vValue`/`sErr` 等框架变量当保留字拒绝，`NumberToStringEx(vValue,...)` 等合法写法被误拒 | 拆分 `RESERVED`（控制关键字，拒绝）与 `RESERVED_VARS`（可读、不可作变量名） | `test_safe_expressions_accepted` 含该用例；`test_unsafe_expressions_rejected` 含 `If(...)` |
| B-11 | 生成的代码草案不标记过期，改完映射仍显示上一次结果 | 关系对象持久化 `generated`（含 `design_fingerprint`）；新增 `/api/workbench/design/stale`；关系行显示「⚠ 已过期」 | `test_stale_detection_after_design_change`、`test_api_stale_endpoint_reports_changed_relation`、浏览器「设计变更后标记代码草案已过期」 |

### LOW（记录，未改）

- 代码生成未做 TI 语法解析，`static check` 只覆盖结构（参数个数/顺序/映射完整性）。
- 关系通过下拉建立，无拖拽连线（设计取舍，非缺陷）。
- `LOOKUP` / `FROM_CONTEXT` 只保存意图，生成时阻断，UI 已说明。
- 单次查询最多解析 12 个 Cube 的 Rule，超限在 `rule_scope.complete` 中标注。

---

## C. 生成器审查

| 维度 | 结论 |
|---|---|
| 表达式安全 | 词法 + 结构校验（非黑名单正则）：白名单函数 8 个、白名单常量 `Now`、`vXxx` 变量、`|` 拼接；拒绝换行、分号、`#`、`=`/`@=`、非白名单标识符、括号前非函数、括号不匹配、结尾残缺。深嵌套 200 层与 2000 项拼接均有界返回。 |
| 变量定义 | 变量名由 `build_var_map` 唯一生成，冲突加 `_2` 并记录；`Value` 等与框架变量同名的维度自动加 `Value` 后缀；未命中来源字段阻断。**四段代码仍不含 Variables 定义**，已通过 `process_config` 明示。 |
| 四段完整性 | prolog（声明/常量/日志/清空/数据源）、metadata（占位 + 注释）、data（转换 + 赋值 + 写入）、epilog（错误处理/事务日志恢复/日志写入）。**依赖 `}APQ` 与 Bedrock，未在 TM1 编译**。 |
| 目标维度顺序 | 写入参数严格按 `tgt_dims` 顺序；Measure 居中、维度交换均有用例。 |
| 数值转换 | 统一 `StringToNumberEx(vXxx, '.,')`（点小数、逗号千分位）。**区域格式、空串、非法字符的实际行为未经 TM1 验证**。 |
| 写入策略 | `overwrite→CellPutN`、`accumulate→CellIncrementN`，与清空策略正交。 |
| 清空范围 | `none` 不产生任何删除语句；`target_scope` 由已确认 Fixed 派生并回显；无法派生即阻断。 |
| 框架依赖 | `dependency_manifest` 区分 BEDROCK 过程、`}APQ` Cube/维度、目标 Cube/维度，并声明「生成完成 ≠ 可独立运行」。 |

---

## D. Blueprint 审查

| 项 | 结论 |
|---|---|
| 角色重绑定 | 按 `dimension_order` 生成，绑定值直接决定维度名与赋值顺序；交换两个维度角色后赋值与代码指纹同时变化。 |
| 跨项目污染 | 项目 B 代码含 `SalesVolume`/`RetailSales.csv`/`vProduct = vSKU;`，不含项目 A 的任何名称；断言在测试与浏览器两侧均有。 |
| 维度顺序 | 保留为有序列表，绑定后重名即阻断。 |
| 指纹覆盖 | 逐一验证 8 个生成相关字段（固定成员 ×2、数值来源、写入策略、清空策略、模板、维度顺序、目标 Cube 名）全部改变指纹；`note` 与 `generated` 不改变。 |
| STALE | 已实现并可持久化；UI 显示「已过期」，避免把旧草案当最新。 |
| 版本保护 | 仍只有 `version` 字段，**无版本差异比较**；删除已有引用保护；导入一律分配新 id，不覆盖本地资产。 |

---

## E. 资产包安全

| 攻击 | 结果 |
|---|---|
| 路径穿越 `../`、反斜杠、绝对路径、盘符、Unicode | 全部拒绝（整包不导入） |
| 非白名单目录 | 拒绝 |
| 条目数 505 | 拒绝 |
| 解压 20 MB（压缩后 12 KB） | 拒绝 |
| Schema 版本不符 | 拒绝 |
| 条目哈希被篡改 | 拒绝该条 |
| manifest 条目缺字段 / 损坏 JSON / 缺 manifest / 非 zip | 拒绝并保持原资产 |
| 同名资产导入 | 分配新 id，不覆盖（导入两次得到 2 个） |
| 往返完整性 | 角色、映射、维度顺序、模板、写入/清空策略全部保留 |
| 导出敏感标记（Pattern 描述、验证契约 label、绝对路径、凭据形态） | public 阻断，private 允许但列出 findings |
| 删除被引用资产 | 409 + 引用项目列表 |

**仍未做**：导出只做正则级内容审查，语义级（例如「这个成员名是否属于某企业」）无法自动判断；UI 在存在 findings 时要求人工确认，但**不构成发布授权**。

---

## F. UI 审查

| 场景 | 结果 |
|---|---|
| 从零建维度/Cube/Schema/关系/映射/生成 | 通过（真实 Chrome，真实输入） |
| 生成面板显示清空范围、数据源变量、未验证声明 | 通过（本轮新增断言） |
| 改固定成员后关系行显示「⚠ 已过期」 | 通过 |
| 不完整配置 | 返回结构化 blockers，逐条中文说明，无 Traceback |
| 非法表达式 | 返回 `UNSAFE_EXPRESSION` 并指出原因 |
| 导出有风险项 | 弹确认，取消则不下载 |
| 刷新恢复（Cube/维度/Schema/关系/映射/Blueprint） | 通过 |
| 切回探索模式后原功能 | 通过（真实对象搜索与详情仍可用） |
| 双击/重复打开产生多弹窗 | 详情面板复用，不叠加 |

---

## G. Portable

| 项 | 结果 |
|---|---|
| 构建 | 成功，`release/portable-20261021-212035` |
| 资源 | `assets.html`、`assets.js/css`、`architecture_workbench.html`、`architecture-workbench.js/css` 均在包内 |
| 启动 | 独立 `TM1_INSIGHT_DATA_DIR` 启动 → `/`、`/assets`、`/architecture?view=workbench` 全部 200 |
| 资产功能 | 便携包内 `POST /api/assets/pattern` 成功，数据写入 `%LOCALAPPDATA%\TM1 Insight\assets`（与安装包分离，升级不覆盖） |
| 客户数据 | 无 `.duckdb`/`.wal`/`.parquet`/`.env`/`workspaces`/`assets`；`contains_customer_data: false` |
| 干净机 | **未验证**（无无 Python/无 Node 的干净 Windows 环境） |

---

## H. 测试

| 项 | 结果 |
|---|---|
| pytest | **1093 collected / 1093 passed / 0 failed / 0 skipped**（152s，基线 1005 + 88） |
| 新增 | `tests/test_rc_attack.py` 88 项 |
| 浏览器（真实 Chrome） | `acceptance_design` 32 项、`acceptance_assets` 17 项、`acceptance_workbench` 37 项、`acceptance_pointer` 10 项，全部通过，失败退出码 1 |
| 便携包 | 构建 + 启动 + 资产写入烟测通过 |
| 未验证 | TM1 编译/执行、`StringToNumberEx` 区域行为、`}APQ`/Bedrock 是否就绪、清空对真实数据的影响、干净机 Portable |

---

## I. GitHub 发布

| 项 | 值 |
|---|---|
| 推送 | 见提交后核对（`origin/codex/engineering-asset-3`） |
| master | `8ef6d67`，未改动 |
| 合并 | **未合并**，按授权范围仅推送开发分支 |
| 历史风险 | `master` 既有 9 个文件含企业对象名、2 份文档含本机绝对路径；本轮未处理，需用户决定（详见 `docs/security/PUBLIC_REPOSITORY_AUDIT.md`） |

**边界声明**：未连接任何 TM1 Server，未读取 Cube Cell，未执行 TI/MDX，未修改正式 DuckDB/WAL，未上传企业数据，未内置 AI，未强推，未改写历史，未合并 master。
