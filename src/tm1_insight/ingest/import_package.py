"""Stream and validate a package into a new private location before selecting it."""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import duckdb


def prepare_import(upload: Path, destination: Path, *, zipped: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if zipped:
        with zipfile.ZipFile(upload) as archive:
            candidates = [entry for entry in archive.infolist()
                          if not entry.is_dir() and entry.filename.lower().endswith(".duckdb")]
            if not candidates:
                raise ValueError("压缩包里未找到 .duckdb 数据库。")
            if len(candidates) != 1:
                raise ValueError("数据包包含多个模型，请分别导入。")
            entry = candidates[0]
            if entry.file_size > shutil.disk_usage(destination.parent).free:
                raise ValueError("可用磁盘空间不足。")
            with archive.open(entry) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
    else:
        os.replace(upload, destination)
    connection = duckdb.connect(str(destination), read_only=True)
    try:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if not {"cubes", "processes", "dimensions"} <= tables:
            raise ValueError("数据库缺少 TM1 Insight 核心对象表。")
        if not connection.execute("SELECT count(*) FROM cubes").fetchone()[0]:
            raise ValueError("数据库没有可用的 Cube 数据。")
    finally:
        connection.close()
