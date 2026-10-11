"""DuckDB 存取层：连接、建表、行数统计。"""
from __future__ import annotations

import duckdb

from tm1_suite.config import Settings
from tm1_suite.store.schema import ALL_TABLES


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def db_path(self) -> str:
        return str(self.settings.db_path)

    def connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        """打开连接。写入用默认，查询可 read_only=True（避免写锁）。

        若库文件尚不存在（尚未 ingest），read_only 模式回退到内存空库并建空表，
        保证全新环境开箱即用、不报「找不到文件」。
        """
        if read_only and not self.settings.db_path.exists():
            con = duckdb.connect(":memory:")
            for ddl in ALL_TABLES.values():
                con.execute(ddl)
            return con
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(self.db_path, read_only=read_only)

    def init_schema(self, drop: bool = False) -> None:
        """建全部表。drop=True 时先删旧表重建。"""
        self.settings.ensure_dirs()
        con = self.connect()
        try:
            for name, ddl in ALL_TABLES.items():
                if drop:
                    con.execute(f"DROP TABLE IF EXISTS {name}")
                con.execute(ddl)
        finally:
            con.close()

    def drop(self, *tables: str) -> None:
        con = self.connect()
        try:
            for t in tables or list(ALL_TABLES):
                con.execute(f"DROP TABLE IF EXISTS {t}")
        finally:
            con.close()

    def table_rows(self, table: str) -> int:
        con = self.connect(read_only=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            con.close()

    def all_rows(self) -> dict[str, int]:
        con = self.connect(read_only=True)
        try:
            return {
                t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ALL_TABLES
            }
        finally:
            con.close()
