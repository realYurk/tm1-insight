"""TM1 Insight Domain Model —— 领域对象定义。

本模块定义 TM1 模型世界的核心语义对象。全部使用 ``dataclass(frozen=True)``
与 ``Enum``，与数据库 / API / Parser / Resolver 完全解耦。

关于三类对象：

A. 基础对象（本次完整定义，字段对齐真实代码契约）：
   Instance / Model / Snapshot / Cube / Dimension / Hierarchy /
   Process / Chore / Rule / Reference / Dependency

B. 轻量定义（定义结构与语义，暂不承载复杂逻辑）：
   Element / Subset / Feeder / Application / Workbook / Worksheet / Lineage

C. 概念占位（仅定义，未来任务实现）：
   Change / Impact / HealthFinding

Reference 与 Dependency 是**两个不同的对象**，不要混为一谈：
- Reference 是语法层事实：「代码里出现了对某对象的引用」，
  直接来自 Parser 产物，携带 evidence（代码位置/操作类型），不判定方向。
- Dependency 是语义层结论：「source 依赖 target」，需经语义判断后得出，
  用 kind 与 confidence 表达。
两者关系是 Reference →(语义解释)→ Dependency。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# 基础类型与枚举
# ---------------------------------------------------------------------------

class ReferenceKind(str, Enum):
    """Reference 的语法类别（对应 Parser 产物中的操作形态）。"""

    CELL_GET = "cell_get"          # CellGetN/S 读引用
    CELL_PUT = "cell_put"          # CellPutN/S、CellIncrementN/S 写引用
    PROCESS_CALL = "process_call"  # ExecuteProcess / RunProcess 调用引用
    RULE_REFERENCE = "rule_reference"  # Rule 中对 Cube 的引用
    DIMENSION_USE = "dimension_use"    # 维度使用引用
    BEDROCK = "bedrock"            # }bedrock.* 框架调用
    OTHER = "other"


class DependencyKind(str, Enum):
    """Dependency 的语义类别（经语义判断后得出）。"""

    PROCESS_CALLS_PROCESS = "process_calls_process"
    PROCESS_READS_CUBE = "process_reads_cube"
    PROCESS_WRITES_CUBE = "process_writes_cube"
    RULE_REFERENCES_CUBE = "rule_references_cube"
    CHORE_RUNS_PROCESS = "chore_runs_process"
    CUBE_HAS_DIMENSION = "cube_has_dimension"
    OTHER = "other"


# ---------------------------------------------------------------------------
# 概念关系层：Instance → Model → Snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Instance:
    """一个 TM1 Server / Planning Analytics 环境。

    对应 AI_INSTRUCTIONS §9 中的 Instance：被分析环境的最外层容器。
    本次只定义概念，不承载连接信息（连接配置属 config.py，不属 Domain）。
    """

    name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Model:
    """Instance 中被分析的一个 TM1 Model。

    一个 Instance 可含多个 Model；Model 是 Snapshot 的直接归属。
    """

    name: str
    instance: Optional["Instance"] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    """某一时刻 Model 的**不可变**快照。

    本次只定义「概念关系」，**不实现**采集 / 存储 / 切换 / 对比。
    快照是不可变历史状态（AI_INSTRUCTIONS §10），旧快照不得被静默改写。
    """

    model: "Model"
    snapshot_id: str                    # 唯一标识（如时间戳 / UUID）
    created_at: Optional[str] = None    # ISO 时间戳，由上层填
    source: str = "tm1"                 # "tm1" / "import" 等
    object_counts: Mapping[str, int] = field(default_factory=dict)  # {cubes: N, ...}


# ---------------------------------------------------------------------------
# 模型对象层
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dimension:
    """一个维度。字段对齐真实 schema（name + elements/subsets 以 JSON 承载）。"""

    name: str
    elements: Sequence[str] = ()         # 元素名列表（轻量表达，不强制完整层次）
    subsets: Sequence[str] = ()          # 子集名列表（轻量表达）
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hierarchy:
    """维度的层级结构。轻量定义：只表达名称与元素序列，不承载 MDX/权重。"""

    name: str
    dimension: str                        # 所属维度名
    elements: Sequence[str] = ()


@dataclass(frozen=True)
class Element:
    """维度层级中的单个元素。轻量定义，不承载属性/类型等复杂逻辑。"""

    name: str
    hierarchy: Optional[str] = None
    parent: Optional[str] = None


@dataclass(frozen=True)
class Subset:
    """维度的子集。轻量定义：名称 + 元素序列。"""

    name: str
    dimension: str
    elements: Sequence[str] = ()


@dataclass(frozen=True)
class Rule:
    """Cube 上的 Rule。轻量定义：原始规则文本 + 引用的 cube。

    本对象不解析 N:/C:/FEEDERS 结构（那是未来 Rule 语义解析任务）。
    """

    cube: str                             # 所属 cube
    statement: str = ""                   # 规则语句文本
    referenced_cubes: Sequence[str] = ()  # 规则中引用的 cube 名


@dataclass(frozen=True)
class Feeder:
    """Rule 的 FEEDERS 语句。轻量定义，仅保留原始文本与目标 cube。"""

    cube: str
    statement: str = ""


@dataclass(frozen=True)
class Cube:
    """一个 Cube。字段对齐真实 schema：name + dimensions（有序）+ rules。"""

    name: str
    dimensions: Sequence[str] = ()        # 有序维度名（对应 cube_has_dimension.dim_order）
    rules: Sequence[str] = ()             # 规则语句文本（轻量表达，不做语义解析）
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Process:
    """一个 TI Process。字段对齐真实 Parser/loader 契约。"""

    name: str
    code: str = ""                        # 完整 TI 代码（prolog+metadata+data+epilog）
    parameters: Sequence[str] = ()        # 形参名列表
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chore:
    """一个 Chore。轻量定义：名称 + 运行的一组 process。"""

    name: str
    processes: Sequence[str] = ()         # 按运行顺序的 process 名
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 前端资产层（轻量定义）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Worksheet:
    """Excel 工作表。轻量定义：名称。"""

    name: str


@dataclass(frozen=True)
class Workbook:
    """前端 Excel 工作簿。轻量定义：名称 + 工作表列表。"""

    name: str
    worksheets: Sequence["Worksheet"] = ()


@dataclass(frozen=True)
class Application:
    """前端应用资产。轻量定义：名称 + 关联的工作簿。"""

    name: str
    workbooks: Sequence["Workbook"] = ()


# ---------------------------------------------------------------------------
# 依赖语义层：Reference → Dependency → Lineage
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reference:
    """语法层引用：代码里出现了对某对象的引用（来自 Parser 产物）。

    字段对齐 hard_extract 的真实输出（operation / target_cube / source_cube /
    callee / dim_args / conditions），并附带 evidence（来源对象 + 快照）。
    **不判定语义方向**——它只是「代码中出现了这个引用」的客观事实。
    """

    kind: ReferenceKind                   # 引用类别
    source: str                           # 来源对象名（如 Process 名）
    target: str                           # 被引用对象名（cube / process / dimension 名）
    operation: str = ""                   # 原始操作（CellPutN / ExecuteProcess / ...）
    evidence: Mapping[str, Any] = field(default_factory=dict)  # 代码位置/行号/快照等

    @property
    def snapshot_id(self) -> Optional[str]:
        """所属快照标识（若 evidence 中携带）。"""
        return self.evidence.get("snapshot_id")


@dataclass(frozen=True)
class Dependency:
    """语义层依赖：source 依赖 target（经语义判断后得出）。

    与 Reference 的区别：Reference 是语法事实，Dependency 是语义结论。
    一个 Dependency 通常由若干 Reference 经语义解释后聚合得出。
    """

    kind: DependencyKind                  # 依赖语义类别
    source: str                           # 依赖方（process / chore / rule / cube）
    target: str                           # 被依赖方（cube / process / dimension）
    confidence: float = 1.0               # 0~1，解析可靠度
    references: Sequence["Reference"] = ()  # 支撑此结论的原始引用（evidence 溯源）
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Lineage:
    """数据血缘（一条 source → target 的传递可达关系）。

    Lineage 是 Dependency（Direct）之上的**传递闭包**推导结果：
    ``A → B``、``B → C`` 两条 Dependency 推导出 Lineage ``A → C``（path=[A,B,C]）。

    字段说明：
    - ``target``：终点对象（关注对象）。
    - ``source``：起点对象（空串表示未指定方向，仅以 target 为中心）。
    - ``path``：完整路径（含起终点），如 ``("A", "B", "D")``，用于解释「为何 A 可达 D」。
    - ``depth``：跳数（direct=1，``A→C`` 为 2，``None`` 表示未计算）。
    - ``dependencies``：支撑这条路径的**直接依赖**（复用 Dependency 的 evidence/references）。

    ``upstream`` / ``downstream`` 为历史字段（target 视角的上下游对象名），
    保留以兼容既有构造，默认空。
    """

    target: str                            # 终点对象（通常是 cube）
    dependencies: Sequence["Dependency"] = ()   # 支撑路径的直接依赖（evidence 溯源）
    upstream: Sequence[str] = ()           # 上游来源对象名（历史字段）
    downstream: Sequence[str] = ()         # 下游受影响对象名（历史字段）
    source: str = ""                       # 起点对象（空 = 未指定方向）
    path: Sequence[str] = ()               # 完整路径（含起终点），如 ("A","B","D")
    depth: Optional[int] = None            # 跳数（direct=1；None=未计算）


# ---------------------------------------------------------------------------
# 未来能力（概念占位，本次不实现）
# ---------------------------------------------------------------------------

class ChangeKind(str, Enum):
    """对象级变化分类（Snapshot Compare 的确定性结论）。"""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class Change:
    """快照间单个对象的差异（对象级、确定性、可解释）。

    由 Snapshot Compare Engine 产出，表达「某个对象在两个 Snapshot 之间发生了什么」。

    字段说明：
    - ``object_name``：对象身份（Process/Cube/Dimension 用 name；Rule 用
      ``(cube, statement)`` 的稳定表达）。
    - ``change_type``：ChangeKind（added / removed / modified / unchanged）。
    - ``before``：变更前的 canonical 对象（added 时为 None）。
    - ``after``：变更后的 canonical 对象（removed 时为 None）。
    - ``object_type``：对象类型（process / cube / dimension / rule）。
    """

    object_name: str
    change_type: str = ""                  # ChangeKind 值：added / removed / modified / unchanged
    before: Any = None
    after: Any = None
    object_type: str = ""                  # process / cube / dimension / rule


class ImpactKind(str, Enum):
    """Impact 的分类（基于 Lineage 的 depth 确定性推导，不做业务猜测）。"""

    DIRECT = "direct"          # depth == 1：source 直接依赖的对象
    INDIRECT = "indirect"      # depth >= 2：沿依赖链传递可达的对象


@dataclass(frozen=True)
class Impact:
    """影响分析结果：一个 source 发生变化时，某个受影响对象的确定性结论。

    由 Impact Analysis Engine 从 ``Lineage``（``get_downstream``）推导，
    不做业务猜测：没有 Dependency → Lineage 就没有 Impact。

    字段说明：
    - ``source``：发生变化的对象（分析起点）。
    - ``target``：受影响的单个对象（终点）。
    - ``kind``：ImpactKind，``direct``（depth=1）/ ``indirect``（depth>=2）。
    - ``depth``：跳数（direct=1，``None`` 表示未计算）。
    - ``path``：完整传播路径（含起终点），如 ``("A","B","C")``，可解释「为何受影响」。
    - ``dependencies``：支撑这条路径的直接依赖（复用 Dependency 的 evidence/references）。
    - ``affected``：历史字段（对象名列表），保留以兼容既有构造，默认空。

    ``kind`` / ``depth`` 是一一对应的：``kind=direct`` 当且仅当 ``depth==1``。
    """

    source: str
    target: str = ""                       # 受影响的单个对象（终点）
    kind: ImpactKind = ImpactKind.DIRECT   # direct / indirect
    depth: Optional[int] = None            # 跳数（direct=1；None=未计算）
    path: Sequence[str] = ()               # 完整传播路径（含起终点）
    dependencies: Sequence["Dependency"] = ()  # 支撑路径的直接依赖（evidence 溯源）
    affected: Sequence[str] = ()           # 历史字段（对象名列表），保留兼容


class HealthSeverity(str, Enum):
    """HealthFinding 的确定性等级（不做 1~100 评分 / Risk Score / AI Score）。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class HealthFinding:
    """模型健康发现：基于确定性证据（Model Object / Reference / Dependency /
    Lineage）得出的结构性问题结论。

    不是业务猜测，也不是评分：每一条 Finding 都能追溯到确定性证据
    （evidence 字段）。核心原则「Absence of evidence is not evidence of
    absence」——只有证据能明确证明问题时才产出 Finding，宁可少报不误报。

    字段说明：
    - ``finding``：人类可读的描述（message）。
    - ``severity``：HealthSeverity（info / warning / error），与规则语义对应。
    - ``affected_objects``：涉及的对象名（历史字段，保留兼容）。
    - ``reason``：确定性证据说明（为何得出此结论）。
    - ``evidence``：结构化证据（如 Reference / Dependency 信息）。
    - ``kind``：Finding 类型标识（如 broken_reference / broken_dependency_target），
      用于确定性排序与分类。
    - ``object``：主体对象名（发现问题的对象，单一主体）。
    """

    finding: str
    severity: HealthSeverity = HealthSeverity.WARNING
    affected_objects: Sequence[str] = ()
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    kind: str = ""                         # Finding 类型标识
    object: str = ""                       # 主体对象名
