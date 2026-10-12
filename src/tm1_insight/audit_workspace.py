"""Per-model frontend paths and private sidecar results. Source databases stay read-only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from tm1_insight.config import Settings
from tm1_insight.store.db import Store
from tm1_insight.store.schema import ALL_TABLES


def identity(settings):
    return hashlib.sha256(str(settings.db_path.resolve()).encode()).hexdigest()[:24]


def preferences_path(settings):
    return settings.user_data_root / "config" / ("audit-" + identity(settings) + ".json")


def preferences(settings):
    try:
        result = json.loads(preferences_path(settings).read_text(encoding="utf-8"))
        if not isinstance(result, dict): raise ValueError()
    except (OSError, ValueError): result = {}
    return {"applications":result.get("applications", str(settings.input_applications_dir)),
            "externals":result.get("externals", str(settings.input_externals_dir)),
            "work_dir":result.get("work_dir", str(settings.user_data_root / "cache" / "frontend"))}


def save_preferences(settings, body):
    values = {}
    for key in ("applications", "externals", "work_dir"):
        raw = str(body.get(key) or "").strip()
        if not raw and key == "externals":
            values[key] = ""; continue
        path = Path(raw).expanduser()
        if not raw or not path.is_absolute(): raise ValueError("请填写绝对目录路径，可选择任意盘符。")
        if key != "work_dir" and not path.is_dir(): raise ValueError("扫描来源目录不存在或不可访问。")
        if key == "work_dir":
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path):
                pass
        values[key] = str(path.resolve())
    state = preferences_path(settings)
    state.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=state.parent, delete=False) as stream:
        json.dump(values, stream, ensure_ascii=False); temporary=Path(stream.name)
    try: os.replace(temporary, state)
    finally: temporary.unlink(missing_ok=True)
    return values


def workspace(settings: Settings, initialize=False):
    from tm1_insight.api.knowledge_tasks import fingerprint
    values = preferences(settings)
    root = Path(values["work_dir"]) / identity(settings) / fingerprint(settings)[:24]
    copy = settings.model_copy(update={"data_dir":root, "database_file":root / "audit.duckdb",
                                      "input_applications_dir":Path(values["applications"]),
                                      "input_externals_dir":Path(values["externals"]) if values["externals"] else root / "unused-externals"})
    if initialize and not copy.db_path.exists():
        source = Store(settings).connect(read_only=True)
        try: cubes=source.execute("SELECT name FROM cubes ORDER BY name").fetchall()
        finally: source.close()
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / ("audit-init-" + uuid.uuid4().hex + ".duckdb")
        pending = copy.model_copy(update={"database_file": temporary})
        con=Store(pending).connect()
        try:
            for ddl in ALL_TABLES.values(): con.execute(ddl)
            con.executemany("INSERT INTO cubes (name) VALUES (?)", cubes) if cubes else None
            con.close()
            os.replace(temporary, copy.db_path)
        finally:
            con.close()
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + ".wal").unlink(missing_ok=True)
    return copy
