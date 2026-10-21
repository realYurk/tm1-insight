# Canvas UX Rebuild — 以 Cube 图标为核心的架构画布

> 本轮唯一目标：把「分析功能页面」改造成**鼠标驱动的架构沙盘**。
> 后端契约（Graph Query / Workspace / Blueprint / CodeGen / 资产库）全部保留，只替换渲染与交互层。

---

## 1. 为什么换掉 Mermaid

上一版 `#ew-graph` 用 Mermaid 生成静态 SVG，再在 SVG 上叠加点击/框选。它能画出关系，但做不到：

| 需求 | Mermaid 方案 | 结论 |
|---|---|---|
| 拖动节点并保存坐标 | 需要改 SVG transform，无布局模型 | 不可行 |
| 鼠标拖线建关系 | 无锚点概念 | 不可行 |
| 自环 / 平行边重合 | 线条重叠后无法命中 | 不可行 |
| 边级点击 + 标签避让 | 依赖 DOM 事件冒泡，命中率低 | 勉强 |
| 千级对象按需探索 | 一次性重排全图 | 差 |

因此渲染层换成 **Cytoscape.js 3.30.2**（MIT，UMD 单文件，离线 vendored 到
`static/vendor/cytoscape.min.js`，许可证见 `cytoscape-NOTICE.txt`）。
只换渲染层：`workbench.py` 的 Graph Query、工作区、Blueprint、CodeGen、资产库一行未动。

---

## 2. 视觉语义（默认视图只画 Cube）

节点类型与图标：

| 类型 | 图标 | 说明 |
|---|---|---|
| `cube` | 蓝色立体方块 | 快照中的真实 Cube |
| `draft` | 琥珀色立体方块（虚线边） | Cube 草稿，未部署 |
| `source` | 紫色文件 | CSV Schema / 数据来源草稿 |
| `group` | 叠层方块 | 折叠后的人工模块 |
| `process` / `chore` / `dimension` | 灰色小方块 | 仅出现在「对象与直接读写」视图 |

连线类型（颜色 / 线型 / 箭头都不同）：

| kind | 样式 | 标签 | 语义 |
|---|---|---|---|
| `TI_CANDIDATE` | 灰色虚线 + vee | `2 TI` / `3 TI`（单条不写标签） | 同一 TI 共同读写；**值流未证明** |
| `RULE_REFERENCE` | 蓝色实线 + tee | `Rule` | Rule 声明式引用，不是装载 |
| `FEEDER_REFERENCE` | 浅色点线 | `Feeder（非值流）` | 只表示依赖触发 |
| `DESIGN_RELATION` | 琥珀虚线 + 三角 | `设计 · 未部署` / `TI Draft ✓` / `TI Draft · 已过期` | 本地设计草稿 |
| `TI_READ` / `TI_WRITE` / `CALL` / `SCHEDULE` | 细灰线 | 读 / 写 | 仅对象视图 |

**事实不被简化成错误结论**：

- 聚合只在同一 TI 的「读 A → 写 B」之间发生，边数据里保留全部 `process_ids` / `process_names`。
- 边标签只显示数量，具体 Process 名在悬停提示与右侧详情里。
- 悬停提示固定写明「值流待核对」；边详情列出 `unresolved_reasons`。
- 自环（同一 Cube 读写自己）用 `loop-direction/loop-sweep` 画成弧线，不隐藏。
- 同一对 Cube 的多条关系用 `control-point-distances` 显式错开 ±18px，各自可点。

---

## 3. 交互清单

| 操作 | 实现 |
|---|---|
| 单击 Cube | 右侧抽屉显示维度顺序、来源标记；画布不重排 |
| Ctrl / ⌘ 单击 | 追加/取消选择（多选） |
| Shift + 拖动 | 框选矩形，命中矩形内节点（`stopPropagation` 防止同时平移） |
| 拖动空白 | 平移画布 |
| 滚轮 | 缩放（0.12–3） |
| 双击节点 | 聚焦（居中并适度放大） |
| 右键节点 | 快捷菜单：聚焦 / 展开上游 / 加入模块 / 隐藏 |
| 点击连线 | 选中并在关系表定位；右侧显示语义与证据 |
| 拖动节点 | 更新坐标 → 写入工作区 `positions` |
| 适应 / ＋ / － / 自动布局 | 工具条；布局用 `breadthfirst`（入口在左，逐层向右） |
| 模块折叠 | 折叠后合并为一个「叠层」图标，点击展开 |

画布容器在 `ResizeObserver` 下自动 `resize`：侧栏/详情开合不会让节点跑到可视区外。

---

## 4. 设计模式：鼠标建模

1. 点 `+ Cube` → 在视口中心放置一个草稿图标，右侧立即打开名称/维度编辑。
2. 悬停任意 `draft` / `source` 节点，右侧出现 `＋` 锚点。
3. 从锚点拖到另一个 Cube 草稿并松手 → 生成 `DESIGN_RELATION` 草稿，自动打开映射面板。
4. 映射面板沿用原有能力：固定成员 / 来源字段 / 表达式（安全子集校验）/ 写入策略 /
   清空策略 / 生成前预检 / CodeGen / 清空范围提示 / 数据源变量契约。
5. 生成成功后边标签变为 `TI Draft ✓`；改动任意影响生成的字段后变为 `TI Draft · 已过期`。

Explore 模式下锚点不可用，事实边不可被拖拽修改。

---

## 5. 工作区契约变化

```python
class Workspace:
    schema_version: Literal['architecture-workspace-1','architecture-workspace-2',
                            'architecture-workspace-3'] = 'architecture-workspace-3'
    positions: dict[str, dict[str, float]] = {}   # 新增：节点坐标，仅展示用途
```

- 旧 v1 / v2 工作区照常加载（`positions` 为空 → 自动布局）。
- `layout` 仍只接受 `{zoom,x,y,vertical}`；画布视口写回 `{zoom,x,y}`。
- 坐标只影响摆放，不参与任何关系判断；`positions` 不进入 `design_fingerprint`。

---

## 6. 验收（真实浏览器 / 真实鼠标）

| 脚本 | 覆盖 | 结果 |
|---|---|---|
| `scripts/acceptance_canvas.py` | 三条演示路径 + 自环/平行边 + 保存恢复 | 全部通过 |
| `scripts/acceptance_pointer.py` | 单击 / Ctrl 多选 / 平移 / 边点击 / 框选 / 拖节点 | 全部通过 |
| `scripts/acceptance_workbench.py` | 37 项（含 TI 源码、写入切面、工作区、模板往返） | 全部通过 |
| `scripts/acceptance_design.py` | 24 项（草稿、映射、生成、过期、刷新恢复） | 全部通过 |
| `scripts/acceptance_assets.py` | 资产库 + Blueprint 复用 | 全部通过 |

截图（`logs/browser_acceptance/`）：

- `50_canvas_explore_node.png`：点击 Cube 看维度，画布保留
- `51_canvas_edge_detail.png`：点击 TI 连线看 Process 与证据
- `52_canvas_connect.png`：鼠标拖线建立设计关系
- `53_canvas_generated.png`：生成后边标签 `TI Draft ✓`
- `55_canvas_loop_parallel.png`：自环 + 平行边分开绘制
- `56_canvas_blueprint.png`：Blueprint 实例化后回到画布

---

## 7. 已知限制（写在这里，而不是假装没有）

1. **对象视图里 TI 仍是节点**（灰色小方块）。这是刻意保留的「高级视图」：
   当用户明确要研究一个 Process 的读写时，把它画成节点比画成边更准确。
   默认 Cube 主干视图不出现 TI 节点。
2. **不画跨 Cube 的值级依赖**。`TI_CANDIDATE` 只表达共同读写，边标签与详情反复声明这一点。
3. **没有自由手绘**：节点不能任意连线到空白处新建对象，只能连到已有草稿。
4. **自动布局只有 `breadthfirst` / `grid`**，没有力导向（避免大图抖动）。
5. **模块折叠是视觉折叠**：折叠后成员对象仍在工作区里，只是不参与当前绘制。
6. Cytoscape.js 增加约 373 KB 静态资源；已随包提供 MIT 许可证。
