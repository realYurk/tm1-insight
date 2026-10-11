"""TM1 Insight Domain Model。

本包定义 TM1 模型世界的**领域对象**，与数据库 / API / Parser / Resolver 解耦。

设计原则（对齐 AI_INSTRUCTIONS.md §9、§39 Era 0）：
- 纯 Python 数据结构（dataclass / Enum），不引入 ORM / DDD 框架。
- 表达「对象是什么」，而非「对象存在哪张数据库表里」。
- 不依赖 DuckDB / SQL / Parquet / 文件路径 / HTTP / TM1 REST。
- 冻结（frozen=True）以强调值语义与不可变性，便于未来 Snapshot 复用。

概念关系（自上而下）：

    Instance
       ↓
    Model
       ↓
    Snapshot（不可变，本包仅定义概念，不做采集/存储）
       ├── Cube
       ├── Dimension ── Hierarchy ── Element / Subset
       ├── Process（Rule / Feeder 附属于 Cube）
       ├── Chore
       └── Application ── Workbook ── Worksheet

依赖语义链：

    Reference（语法层：代码里出现了对某对象的引用，带 evidence）
        ↓ 语义解释
    Dependency（语义层：source depends_on target，带 kind/confidence）
        ↓
    Lineage（本包仅定义概念，不实现引擎）
"""
from .model import (
    Chore,
    Cube,
    Dependency,
    DependencyKind,
    Dimension,
    Element,
    Feeder,
    Hierarchy,
    Instance,
    Lineage,
    Model,
    Process,
    Reference,
    ReferenceKind,
    Rule,
    Snapshot,
    Subset,
    Application,
    Workbook,
    Worksheet,
    Change,
    ChangeKind,
    Impact,
    ImpactKind,
    HealthFinding,
    HealthSeverity,
)

__all__ = [
    "Instance",
    "Model",
    "Snapshot",
    "Cube",
    "Dimension",
    "Hierarchy",
    "Element",
    "Subset",
    "Process",
    "Chore",
    "Rule",
    "Feeder",
    "Application",
    "Workbook",
    "Worksheet",
    "Reference",
    "ReferenceKind",
    "Dependency",
    "DependencyKind",
    "Lineage",
    "Change",
    "ChangeKind",
    "Impact",
    "ImpactKind",
    "HealthFinding",
    "HealthSeverity",
]
