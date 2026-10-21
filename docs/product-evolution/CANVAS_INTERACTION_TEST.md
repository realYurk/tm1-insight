# Canvas Interaction Test — 真实鼠标与键盘操作验收

全部操作使用真实 Chrome + Playwright 真实输入事件（`mouse.move/down/up`、
`keyboard.press`），坐标取自应用自身给出的渲染包围盒；不使用 DOM 事件派发冒充。
脚本：`scripts/acceptance_canvas.py`、`acceptance_pointer.py`、`acceptance_excellence.py`、
`acceptance_workbench.py`、`acceptance_design.py`。运行：`TM1_BASE=http://127.0.0.1:8011 python scripts/<脚本>`。

## A. 画布基础（acceptance_canvas.py，30 项，全部通过）

- Cube 图标渲染、无 Mermaid 静态图；默认视图只画 Cube（TI 不是同级方框）。
- 点击 Cube → 右侧 Inspector 显示维度；点击连线 → 关系语义（候选/Rule 区分）。
- **关闭详情后缩放保持**（1.150 → 1.150），画布占满主区域。
- 设计模式：`+ Cube` 建草稿 → 悬停出锚点 → **真实鼠标拖线**（按下出现预览线，
  分 10 步移动到目标松手）→ 自动打开映射 → 4 行映射 → 生成 TI 草案
  （标注未部署 / 清空范围 / 未在 TM1 验证）→ 连线标签变 `TI Draft ✓`。
- 保存 → 刷新 → 草稿、设计连线、**节点逐点位置一致**恢复。
- 自环渲染为自环；同一对 Cube 的多条关系分开绘制（包围盒不重合）。
- Blueprint 实例化回画布：Cube 草稿 + CSV 来源图标 + 设计连线。

## B. 像素级指针交互（acceptance_pointer.py，10 项，全部通过）

- 节点单击选中、Ctrl 多选（≥2 个 `cn-selected`）。
- 空白拖动平移（真实 mouse down/move/up，pan 变化）。
- 连线点击（边中点像素命中，13px 透明命中带）。
- Shift + 框选（与平移不冲突，marquee 不触发画布移动）。
- 拖动节点（连接线实时跟随，释放后位置入工作区）。

## C. 外壳交互（acceptance_excellence.py，16 项，全部通过）

- **Esc** 关闭详情；**Ctrl+S** 保存工作区（应用栏状态 `saved`，不触发浏览器另存）。
- 底部 Dock：研究笔记页签展开 MDX 输入、可收起；图例可折叠。
- 资源栏折叠（状态记忆），紧凑窗口让位画布。
- 语义缩放：zoom<0.55 隐藏边标签，恢复后还原（10 → 0 → 10）。

## D. 语义与证据（acceptance_workbench.py，37 项，全部通过）

- 候选关系明确标注"值流待核对"；Rule 引用与 Feeder 语义独立；
- 写入切面面板：固定目标成员（如 `Cost Center = No Cost Center`）、
  运行时坐标（`vYear/vMonth…`）、源码值表达式（`vAmount`）原样显示，未确认项有标注。
- 关系表 ↔ 图联动；人工模块标注为人工解释；MDX 只保存不执行。

## E. 设计与资产（acceptance_design.py 32 项 / acceptance_assets.py 17 项，全部通过）

- 维度草稿 / Cube 草稿 / CSV Schema 全流程；映射与代码生成。
- Blueprint 提炼 → 资产页可见 → 项目 B 绑定 → 生成代码未残留项目 A 对象名 →
  导出 zip → 导入 → 刷新仍在。

## F. 已知交互限制

- 无 Ctrl+Z 撤销（没有可靠命令历史，不伪造按钮）。
- 模块折叠仍是视觉折叠（成员隐藏），非图分组布局。
- 触屏 / 手写笔未测试（目标平台为 Windows 桌面鼠标）。
