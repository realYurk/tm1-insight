"""pytest 共享 fixture。

只负责把 src/ 加入 import 路径，让 tm1_suite 包可导入。
不连接任何真实 TM1 Server、不触碰 data/ 下的生产 DuckDB / raw / parquet。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 项目根目录（本文件位于 <root>/tests/ 下）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def make_ti():
    """构造 TI 的 dict（对应 raw JSON 结构），便于写最小可复现片段。

    返回一个工厂函数：传入 prolog/metadata/data/epilog/parameters，
    得到 process_ti 需要的 ti_json dict。
    """

    def _make(
        prolog: str = "",
        metadata: str = "",
        data: str = "",
        epilog: str = "",
        parameters: list | None = None,
        name: str = "TestProcess",
    ) -> dict:
        return {
            "name": name,
            "prolog": prolog,
            "metadata": metadata,
            "data": data,
            "epilog": epilog,
            "parameters": parameters or [],
        }

    return _make
