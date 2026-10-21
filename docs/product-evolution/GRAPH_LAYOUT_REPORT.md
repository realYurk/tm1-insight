# Graph Layout Report — 布局引擎与真实图测试

实现：`src/tm1_insight/api/static/canvas-layout.js`（纯函数，不依赖 Cytoscape，可独立测试）。
入口：`window.TM1CanvasLayout.compute(nodes, edges, opts)` → `{positions, strategy, sccCount}`。

## 1. 算法

### 形态判定
1. Tarjan SCC（迭代实现，深图不爆栈）收缩强连通分量 —— 循环关系不强行 DAG。
2. Hub 检测：最大度节点满足 `deg ≥ 5 且 deg ≥ 0.34·N` → **辐射布局**（radial）。
3. 否则 → **分层布局**（layered）。

### 辐射布局（中心 + 同心环）
- Hub 居中；邻居按 id 稳定排序后均匀分布在第一环
  （半径 `max(235, N·124/2π + 60)`，弧长 124px/节点保证长标签不碰撞，纵向 0.86 压扁）。
- 二度邻居挂外环，锚定其环上邻居的角度。
- 适合"一个中心 Cube + 几十个读写对象"的典型 TM1 形态。

### 分层布局（加工链）
- 分量 DAG 上 Kahn 拓扑 + 最长路径分层（Source → 中间 → Target，自左向右）。
- 层内重心（barycenter）迭代 3 轮减少边交叉；每层宽度按最长节点名估宽。
- 行距 96px（节点 58 + 标签 + 呼吸）；单列超 9 行自动分栏，避免超高竖列。
- 多成员分量（环）围绕格中心成小环放置。

### 碰撞治理
- 网格/层距按节点名估宽（`64 + len·6.2`，上限 240）而非固定值；
- 辐射环弧长按最长标签校准（124px，由真实 17 邻居图验证）。

## 2. 真实图测试（Demo 模型，1920×1080，真实 Chrome）

### 用例 A：General Ledger（中心 + 17 邻居，18 条关系，含自环与 Rule）
- 策略：radial。客观指标（`acceptance_excellence.py` LAYOUT_METRICS）：
  - 节点/标签重叠对：**0**（改造前：底部一行全部互相重叠）
  - 被画布裁切节点：**0**（改造前：部分节点超出可见区）
  - 宽高比：**1.17**（改造前：约 6:1 一字长蛇阵）
- 截图：`logs/browser_acceptance/60_hub_radial_1920.png`（改造前对照 `logs/round0/workbench_1920.png`）。

### 用例 B：链状图（Sys Definition → CM Sales Assumption → CM Project Plan）
- 策略：layered，三列自左向右，位置 {0,0} → {410,0} → {762,0}，无交叉。

### 用例 C：三档分辨率
- 1920/1600/1366 全部 `overlap=0, clipped=0`（62_compact_1366.png）。

## 3. 布局稳定性

- 用户拖动节点后位置写入工作区（`positions`），刷新恢复；保存的视口（zoom/pan）优先于自动 fit。
- 自动布局**不会**在用户手动平移/缩放后偷偷覆盖视口：程序化 fit/缩放打 `programmatic`
  标记，用户滚轮/拖拽平移置 `userView`，此后 ResizeObserver 不再自动重适配。
- 新查询/局部展开后的"安定窗口"（2.5s）内容器尺寸变化会自动重新适应，
  保证详情面板开合不会把节点挤出可视区。

## 4. 已知限制

- 分层布局的分栏阈值（9 行）为经验值，超大层（>30 节点）可能产生多栏并列。
- 环（SCC）成员的小环排布未做交叉优化，边可能穿过环心。
- 未引入 ELK/Dagre 等外部库（避免 373KB 之外的新静态资源）；若未来需要
  正交路由/端口对齐，建议再评估 ELK.js。
