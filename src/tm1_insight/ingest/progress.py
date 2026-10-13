"""Real stage/object counters. Stage position is never an overall time percentage."""
from __future__ import annotations

from typing import Callable, Optional

Progress = Callable[[str, Optional[int], Optional[int]], None]

INGEST_STAGES = (
    ("enumerate", "连接并读取对象目录"), ("security", "读取安全元数据"),
    ("cubes", "采集 Cube 与规则"), ("processes", "采集 TI 进程"),
    ("dimensions_business", "采集业务维度"), ("dimensions_system", "采集系统维度"),
    ("chores", "采集 Chore"), ("raw_index", "保存采集索引"),
    ("load_raw", "读取采集文件"), ("load_objects", "建立对象表"),
    ("load_dimensions", "建立维度表"), ("relations", "解析结构引用"),
    ("lineage", "解析 TI 写入点"), ("parquet", "导出 Parquet"),
    ("validate", "校验新模型"), ("activate", "切换到新模型"),
)
AUDIT_STAGES = (
    ("prepare", "准备独立扫描工作区"), ("enumerate", "整理文件清单"),
    ("scan", "扫描前端文件"), ("save", "事务保存扫描结果"),
)


def stage_progress(stages, phase: str, done=None, total=None) -> dict:
    index = next(index for index, (key, _) in enumerate(stages) if key == phase)
    return {"phase": stages[index][1], "stage": index + 1, "stages": len(stages),
            "done": done, "total": total,
            "percent": round(100 * done / total, 1) if total and done is not None else None}
