# Cube 血缘：人读 Markdown 闭环

日期：2026-10-25。目标是让已核对的关系与切面离开网页后仍能阅读；所属产品层为 Lineage & Relationships / Architecture Explorer。不增加 Parser、计算语义、业务推断、独立页面或远程访问。

## 审计结论与复用

检查 PRODUCT_CONSTITUTION.md、AGENTS.md、cube-lineage.js、Cube 模板、Workbench detail/writes/rules 接口和既有测试。原页面已通过现有 Calculation 的 read_nodes / coordinate_mapping 及 Rule IR 展示切面，导出却只有关系清单加原始 JSON，没有把已核对内容转成人读正文。

本轮只补导出展示投影。源码入口仍复用既有 Process 源码页；未增加新的源码 API，不扩大分析范围。

## 实际文件

- `src/tm1_insight/api/static/cube-lineage.js`：新增纯展示函数 markdownReport，复用 slices、writeRows、操作中文标签和源码位置。导出按钮使用同一函数。没有重复构建语义事实。
- `src/tm1_insight/api/templates/cube_lineage.html`：控制器资源版本 v9。
- `tests/test_cube_lineage_ui.py`：新增两项导出测试，并将原入口一致性断言适配 Markdown 转义；保留全部旧测试。
- 本报告。

## 导出结构与兼容性

1. 范围、截断与 Cube 关系表。
2. 已核对的逐写入点摘要：TI、Section:行:列、覆盖/累加、值表达式、该候选源 Cube 的读取切面、目标切面和证据边界。
3. 已核对 Rule 摘要：位置、原始目标区域、已确认 DB 源 Cube、条件、表达式摘录、中文解析边界。Rule 不作为 TI 写入操作。
4. `<details>` 技术附录，保留原 `cube-lineage-review-1` JSON 字段：snapshot_id、query、limits、relations、inspected。完整已核对证据不删除，不是全模型导出。

检查记录按关系/Process 稳定排序，与点击先后无关。人读文字转义 Markdown 特殊字符；条件段落在整张写入表之后，避免打断多写入点表格。

单条坐标最多摘录 6 项，每个写入最多展示 4 处相关读取，单字段最多 240 字符；超出时标明摘录及附录。附录保留原始完整值。未主动核对时明确只有索引/引用关系，不补造切面。

## 实际合成验收

浏览器在隔离 8807 服务选择 Cube_B，核对 Multiple 和 RuleOutput，然后真实点击导出。最终下载文件为 Cube-Lineage (5).md，复制到独立产物目录保存。

- Multiple data:1:72：a*2；保留 Cube_A data:1:3 的读取依赖；Year=pYear 动态，目标 Region=Member1 / Measure=Member2 固定。
- Multiple data:1:121：vUnknown；本表源切面未确认；目标 Region=Member2 / Measure=Member1。没有继承前一个写入的来源。
- RuleOutput Rule:1:1：DB 引用 Cube_B，原区域 Member1 的维度归属仍待确认；正文显示“部分解析；未确认项见附录”。没有把裸成员自动映射为某个维度。
- 以本机已有 markdown-it 渲染器独立验证下载文件：3 张表格，1 个折叠技术附录，转义后的 Cube_A 和 a*2 渲染文本正确。未将该校验库新增为产品/测试依赖。
- JSON 附录核对：4 条关系、2 个独立 TI 写入点、Rule.status=PARTIAL；第二个写入 source_reads 为空，原 schema 不变。

产物目录：`<local-acceptance>/cube-human-export/`。

包含 Cube-Lineage.md、verification.json、export-evidence-page.png、export-payload.json、measure-export.cjs、regression.txt。均为合成数据。

## 测试、体积与性能

运行器：`.venv\Scripts\python.exe scripts/run_offline_tests.py`，临时用户目录并阻断外网。

- 导出/查询/切面专项 `-q tests/test_cube_lineage_ui.py`：13 passed, 1 warning，2.87s；增加逐 Rule 解析边界后 4.36s；最终来源范围措辞专项复跑 13 passed, 1 warning，4.02s。
- 全量 `-q`：1122 passed, 0 failed, 1 warning，134.22s。来源范围措辞的最后调整另经上述最终专项验证。
- `node --check`、`git diff --check` 通过；仅既有 workflow.py 换行提示。
- 唯一警告为既有 Starlette TestClient/httpx 弃用提示。初次专项的两个失败是转义后的对象名断言仍使用未转义文本，已修正断言并保留身份一致性验证，没有删除测试。
- 最终下载 27221 字节，人读部分 2003 字节，技术 JSON 25095 字节。已核对内容与上一轮相同；主要增加的是人读摘要。
- 使用实际下载的合成证据，Node 进程内生成 100 次（不含启动）：中位 0.084ms、最大 0.9563ms。仅为小样本序列化测试，不代表大型真实模型性能。

## 安全与未确认边界

未连接 TM1 Server、读取业务单元格或修改正式数据库。合成 DuckDB SHA256 仍为 117CC5015D95B310268008714B9A385BD6267AE132FDF4F65BFE0F16115D9E33；workspace 写入请求 0。导出不新增网络请求、不重新读取全模型。

源切面正文只投影当前写入保留读取节点的坐标。没有这些节点不能否定其他值来源；Data Row Binding 等证据仍完整保留在附录，本轮未新增其人读坐标投影。静态依赖不证明运行贡献、条件可达性或逐单元格映射；技术附录的折叠效果取决于 Markdown 阅读器支持。

分支 codex/canvas-excellence-04，HEAD 24ef873c24c75a6042f068330914526dadca69b6。保留全部旧未提交成果，无提交、推送、合并。

下一项高价值闭环：在相同证据约束下，复用既有 Data Row Binding 结果补人读来源说明，或为源码页提供带模型身份校验的 Section/行定位；需先核对现有源码定位契约，不新建解释器。


公开版说明：`<local-acceptance>` 表示本机隔离验收目录；截图、下载样例、模型和原始日志均不随仓库发布。
