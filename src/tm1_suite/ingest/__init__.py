"""采集与入库。

子模块（exporter/loader）按需导入，避免把 TM1py（依赖 asyncio）拉到只读查询路径里。
"""
from typing import Any

__all__ = ["Exporter", "Loader"]


def __getattr__(name: str) -> Any:
    if name == "Exporter":
        from tm1_suite.ingest.exporter import Exporter

        return Exporter
    if name == "Loader":
        from tm1_suite.ingest.loader import Loader

        return Loader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
