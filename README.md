# tm1-suite

> IBM Planning Analytics / TM1 的元数据工作台：**离线浏览 · 血缘追踪 · 代码生成 · 前端资产审计**，一站式。

把 TM1 模型里那些"藏在代码里的关系"挖出来，用可视化界面讲清楚：**这个数是谁算出来的、数据从哪个 Cube 搬过来、哪个 TI 在写、哪个前端页面在展示**。

---

## 这是什么

TM1 模型的痛点：对象成百上千、TI 代码互相调用、Rule 层层计算、数据源头难以追溯。**tm1-suite** 把 TM1 的全部元数据（Cube / 维度 / TI 进程 / Chore / Rule / 前端 Excel 资产）抽取到本地一份 **DuckDB + Parquet** 仓库，然后提供：

| 能力 | 说明 |
|---|---|
| 🔍 **语句级血缘** | 反查"某个值是谁写的"：解析 TI 里 `CellPut*` / `CellGet*` 的每一句，追到具体维度切面、来源变量、写入前提 |
| 📊 **MDX 反查** | 粘贴一段 MDX，自动解析目标 Cube + 筛选条件，按相似度找出最可能写入的 TI |
| 🕸️ **知识图谱** | 以 TI 为中心，看它往哪个 Cube 的哪个切面写数据，上下游调用链一目了然 |
| ⌨️ **代码生成** | 生成标准 TI 框架代码（数据传输 / 数据导出 / 维度维护 / 环境初始化） |
| 📄 **前端资产审计** | 扫描前端 Excel，自动建立"前端页面 → 后端 Cube"映射，标出断链 / 含 TM1 公式的资产 |

**离线优先**：数据抽到本地后，所有分析都在本地跑，**不需要连 TM1 服务器**。

---

## 快速开始（3 步）

### 前置条件

- Python **3.9+**（推荐 3.11）
- 能连 TM1 的网络（仅首次拉数据需要；之后离线用）

### 第 1 步 · 安装

```bash
git clone https://github.com/realYurk/tm1-suite.git
cd tm1-suite

# 安装依赖 + 以可编辑模式安装本包
pip install -e .
```

> 内网环境可用阿里云镜像加速：
> `pip install -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com`

### 第 2 步 · 配置连接（首次拉数据）

```bash
cp .env.example .env
```

用编辑器打开 `.env`，填入你的 TM1 服务器信息：

```ini
TM1_ADDRESS=你的服务器地址
TM1_PORT=30003
TM1_USER=你的用户名
TM1_PASSWORD=你的密码
TM1_SSL=false
TM1_NAMESPACE=你的命名空间（可选）
```

测试连通：

```bash
tm1-suite check
```

看到"连接成功"和对象数量，就说明连上了。

### 第 3 步 · 拉取数据 + 启动

```bash
# 拉取全部元数据并入库（首次约 10-20 分钟）
tm1-suite ingest

# 启动 Web UI
tm1-suite web
```

浏览器打开 **http://localhost:8000** 即可。

> **Windows 一键启动**：也可以直接双击 `start.bat`，它会自动装依赖、自动开浏览器，全程不用敲命令。

---

## 使用手册

### 首页（`/`）

- **全局搜索**：输入 Cube / TI 进程 / Chore 名字，实时联想，回车直达详情页。
- **三个任务入口**：查血缘（MDX 反查）、查对象（浏览 Cube/TI）、写代码（代码生成）。
- **MDX 反查**：粘贴一段 MDX，自动找出"最可能写入这个交叉点的 TI"。
- **数据规模**：一眼看清库里的 Cube / 维度 / TI / Chore / 血缘流 / 前端映射数量。

### Cube 浏览（`/cubes`）

全部 Cube 列表，支持搜索、分页。点进任意 Cube 详情页，能看到：

- **维度结构**：每个维度一行，右侧展示元素示例。
- **数据从哪来**：数据流向图 —— 源头 Cube → 搬运 TI → 本 Cube。
- **谁写入它**：每个写入 TI 按"差异维度"折叠，看清写入点、来源变量、写入前提。
- **谁读它**：下游读取该 Cube 的 TI 列表。
- **前端展示**：该 Cube 是否在某个前端 Excel 页面直接呈现。
- **规则**：Cube 的 Rule 代码，语法高亮。

### TI 进程（`/processes`）

全部 TI 进程 + Chore 列表。点进 TI 详情页：

- **参数 / 变量 / Prolog / Metadata / Data / Epilog** 分 Tab 浏览，代码语法高亮 + 行号。
- **代码搜索**：右侧栏搜索关键字，跨所有 Tab 定位，↑↓ 切换命中。
- **数据源头**：该 TI 读取 / 写入的 Cube。
- **调用关系**：谁调用它、它调用谁（递归树）。

### 知识图谱（`/graph`）

输入一个 TI 进程名，以它为中心展示：

- **写入切面**：它往哪个 Cube 的哪个切面写数据（维度、来源变量、取值、写入前提）。
- **上游 / 下游调用链**：递归展开，点击任意节点可"以此为心"重新聚焦。

### 代码生成（`/codegen`）

生成标准 TI 框架代码，包括：

- **数据传输**：Cube A → Cube B，自动补全变量、维度映射、CellGet/CellPut。
- **数据导出**：Cube 导出 / 维度导出（CSV / 文本）。
- **维度维护**：增删维度元素。
- **环境初始化**：`}APQ Settings` 等参数 Cube 的初始化代码。

生成的是 **Cubewise APLIQODE 框架**风格的标准代码，可直接复制到 TM1 使用。

### 前端资产（`/audit`）

扫描本地前端 Excel（`applications/` 与 `externals/` 目录），产出：

- **统计卡片**：资产数、映射数、含 TM1 公式数、高风险 / 断链数。
- **前端 → 后端映射表**：每个菜单/文件对应哪些后端 Cube。
- **资产风险表**：按风险等级 / 是否含 TM1 / 是否断链筛选。

### 连接设置（`/settings`）

配置 TM1 连接、重新拉取元数据、重新扫描前端资产。

---

## CLI 命令速查

```bash
tm1-suite status            # 查看各表行数与数据库路径（离线可用）
tm1-suite query "<Cube名>"  # 查某个 Cube 的读写者 + 维度（离线可用）
tm1-suite audit             # 重扫前端 Excel 资产（离线可用）
tm1-suite ingest            # 拉取 + 入库（需要连 TM1）
tm1-suite ingest --no-export  # 不重新拉取，仅用已有 raw 数据入库
tm1-suite check             # 测试 TM1 连接
tm1-suite web               # 启动 Web UI
```

---

## 新机器快速部署

**场景 A：已有数据包（最常见）**

同事把整个项目目录（含 `data/`）打包给你：

```bash
# 1. 解压到任意目录，进入
cd tm1-suite

# 2. 装依赖
pip install -e .

# 3. 直接启动（无需连 TM1）
tm1-suite web
```

**场景 B：纯程序，自己连 TM1 拉数据**

```bash
git clone https://github.com/realYurk/tm1-suite.git
cd tm1-suite
pip install -e .
cp .env.example .env   # 填真实连接信息
tm1-suite check        # 测连通
tm1-suite ingest       # 拉数据
tm1-suite web          # 启动
```

**场景 C：Docker**

```bash
docker compose up -d
# 首次需手动入库：
docker compose run --rm tm1-suite ingest
```

---

## 项目结构

```
tm1-suite/
├── src/tm1_suite/
│   ├── api/            # FastAPI Web UI（路由 + Jinja2 模板 + 静态资源）
│   ├── cli.py          # CLI 入口（typer）
│   ├── config.py       # 配置（.env 加载）
│   ├── ingest/         # 数据抽取（exporter/loader/lineage/audit）
│   ├── store/          # DuckDB 存储 + 查询 + 代码生成
│   └── tm1/            # TM1py 客户端封装
├── data/               # 本地数据仓库（不入库，见 .gitignore）
├── start.bat           # Windows 一键启动
├── make_release.py     # 打包脚本（程序体 / 数据体分离）
├── Dockerfile / docker-compose.yml
├── requirements.txt / pyproject.toml
└── README.md
```

---

## 打包分发

项目内置 `make_release.py`，把发布拆成"程序体"和"数据体"：

```bash
python make_release.py                # 程序体 + 数据体
python make_release.py --app-only     # 只打程序体（源码，更新低频）
python make_release.py --data-only    # 只打数据体（duckdb + inputs，随 TM1 更新）
```

- **新用户**：解压程序体 + 数据体到同一目录，双击 `start.bat` 即可。
- **更新数据**：只替换数据体（解压覆盖 `data/`），程序体不动。
- **更新程序**：只替换程序体，数据体不动。

---

## 常见问题

**Q：离线能用吗？**
A：能。只要本地有 `data/`（之前拉过数据），所有分析都在本地跑，不连 TM1。

**Q：`tm1-suite` 命令找不到？**
A：确认 `pip install -e .` 成功；或改用 `python -m tm1_suite.cli <命令>`。

**Q：Chore 步骤为空？**
A：Chore 步骤数据需在拉取元数据时展开。重新 `tm1-suite ingest` 即可填充。

**Q：怎么更新数据？**
A：连上 TM1 后重新 `tm1-suite ingest`；或直接替换别人打包好的 `data/` 目录。

---

## 免责声明

- **本项目是独立的第三方工具**，与 IBM 无任何隶属、授权或背书关系。
- **TM1 / IBM Planning Analytics 是 IBM 的商标**，本项目仅作为其生态的辅助工具使用。
- 本软件按"现状"提供，作者不对因使用本软件造成的任何损失承担责任。
- 使用前请确保你有权访问所连接的 TM1 服务器及数据。
- 详细授权条款见 [LICENSE](LICENSE)。
