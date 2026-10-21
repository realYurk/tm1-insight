# ASSET_PACKAGE_SPEC — 资产包格式与安全限制

> 代码：`src/tm1_insight/asset_package.py`
> 测试：`tests/test_assets.py`（导出预检、路径穿越、校验和、大小上限、版本）

## 1. 结构

```
tm1-insight-assets.zip
├── manifest.json          # schema、范围、条目、sha256
├── README.txt             # 说明与使用提示
├── blueprints/<id>.json
├── patterns/<id>.json
└── verifications/<id>.json
```

`projects/` 目录在白名单中（导入允许），但**导出默认不包含项目实例**——它们含具体绑定与工作区引用。

## 2. manifest.json

```json
{
  "schema": "engineering-asset-package-1",
  "visibility": "private",
  "created_at": "2026-10-21T12:00:00+00:00",
  "tool": "TM1 Insight",
  "items": [
    {"kind": "blueprint", "id": "bp3-…", "name": "…", "file": "blueprints/bp3-….json",
     "sha256": "…"}
  ]
}
```

- `schema` 固定；导入时版本不符直接拒绝。
- 每个条目的 `sha256` 是文件字节哈希，导入时逐条校验。

## 3. 内容边界

**包含**：角色定义、维度顺序、映射方式、固定成员值、模板 id/版本、写入与清空策略、验证要求。

**不包含**：

- 企业 TI / Rule 源码正文；
- Snapshot、DuckDB、WAL、parquet；
- 数据行、连接字符串、凭据；
- 工作区文件（`workspaces/`）；
- 本机绝对路径（导出审查会阻断）。

注意：固定成员与维度名称本身可能反映业务结构，因此它们被视为**需要人工确认**的内容，而不是"安全内容"。

## 4. 导出范围与预检

| 范围 | 行为 |
|---|---|
| `private` | 允许导出；预检结果作为提示（`FIXED_MEMBERS`、`BUSINESS_NAMES`、`PROJECT_REFERENCE` 为 WARNING） |
| `public` | 任一 BLOCKER 存在则**拒绝导出**，返回原因 |

BLOCKER 判定：

| code | 触发 |
|---|---|
| `RESTRICTED_SOURCE` | Blueprint 标记为含项目信息（`restricted=true`） |
| `ABSOLUTE_PATH` | 任一层级出现 `D:\`、`D:/`、`/home/`、`/Users/` |
| `CREDENTIAL_LIKE` | 出现 `password/secret/api_key/Bearer …` 等形态 |

预检结果在 UI 中逐条展示（含路径与建议），不复制具体敏感原文到导出包。

## 5. 导入校验

| 检查 | 失败行为 |
|---|---|
| 包大小 > 5 MB | 拒绝 |
| 不是 zip | 拒绝 |
| 缺少 `manifest.json` | 拒绝 |
| 条目路径含 `..`、绝对路径、盘符 | 整包拒绝（不落盘） |
| 条目不在白名单目录 | 整包拒绝 |
| `schema` 版本不符 | 拒绝 |
| 条目哈希不匹配 | 该条跳过并报告 |
| 内容不符合模型契约 | 该条跳过并报告 |

导入**一律分配新 id**，不覆盖本地同名资产；`origin` 标记为 `IMPORTED`。

导入成功 ≠ 可在当前项目生成正确实现：仍需重新绑定角色、通过预检。

## 6. 为什么不做"自动脱敏后即可公开"

- 名称是否敏感、能否公开，是**授权判断**，不是正则能决定的；
- 因此系统提供"私有导出"作为默认路径，公开导出只做**阻断**，不做"自动放行"；
- 用户可以选择私有资产包外带，但不能因为工具没报错就推定拥有公开权。

## 7. 未实现

- 包签名 / 发布者身份（无 PKI）；
- 增量包与差量升级；
- Blueprint 版本迁移脚本（只做版本号校验）；
- 项目实例导出（结构上允许导入，导出未开放）。
