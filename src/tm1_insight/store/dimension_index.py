"""Disposable index for one large dimension, isolated by model fingerprint.

Uses the existing bounded TaskManager and artifact cache; never changes the source.
Only batches of 1000 normalized rows cross into Python. Derived records retain
original positions, including malformed entries; no MDX or weight inference.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
import tempfile
import threading
from pathlib import Path

from tm1_insight.tasks import TaskManager, ResultArtifact
from tm1_insight.store.db import Store
from tm1_insight.store import dimensions
from tm1_insight.learning.pages import index_path

VERSION = "dimension-index-1"
THRESHOLD = 50_000
CACHE_BYTES = 1024 * 1024 * 1024
_manager = None
_lock = threading.Lock()


def manager(settings):
    global _manager
    root = settings.user_data_root / "cache" / "dimension-index"
    with _lock:
        if _manager is None or _manager.root != root:
            if _manager is not None:
                _manager.close()
            _manager = TaskManager(root, max_records=16, max_cache_bytes=CACHE_BYTES)
        return _manager


def key(name):
    return json.dumps({"engine": VERSION, "dimension": name}, sort_keys=True)


def path(settings, name, source):
    digest = hashlib.sha256((source + "\0" + key(name)).encode()).hexdigest()
    return settings.user_data_root / "cache" / "dimension-index" / (digest + ".json")


def cached(settings, name, source):
    header = path(settings, name, source)
    try:
        value = json.loads(header.read_text(encoding="utf-8"))
        if value["version"] != VERSION or value["source"] != source or value["dimension"]["name"] != name:
            return None
        if any(not isinstance(value["dimension"]["fields"][field]["count"], int) for field in dimensions.FIELDS):
            return None
        with closing(sqlite3.connect(index_path(header).resolve().as_uri() + "?mode=ro", uri=True)) as con:
            stored = con.execute("SELECT value FROM meta WHERE key='source'").fetchone()
            if not stored or stored[0] != source:
                return None
            con.execute("SELECT position FROM items LIMIT 1").fetchone()
        return value, header
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return None


def build(settings, name, source, meta, progress, source_valid):
    root = settings.user_data_root / "cache" / "dimension-workers"
    root.mkdir(parents=True, exist_ok=True)
    owner = tempfile.TemporaryDirectory(dir=root)
    header = Path(owner.name) / "dimension.json"
    destination = index_path(header)
    source_con = None
    target = None
    try:
        progress(stage="准备当前维度索引", stage_index=1, current=0, total=None)
        if not source_valid():
            raise ValueError("Source changed")
        source_con = Store(settings).connect(read_only=True)
        target = sqlite3.connect(destination)
        target.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        target.execute("INSERT INTO meta VALUES ('source', ?)", [source])
        target.execute("""CREATE TABLE items(field TEXT, position INTEGER, payload TEXT,
            name TEXT, parent TEXT, component TEXT, search TEXT, PRIMARY KEY(field,position))""")
        labels = {"elements": "索引元素", "edges": "索引直接上下级", "attributes": "索引属性定义", "subsets": "索引子集定义"}
        for stage, field in enumerate(dimensions.FIELDS, 2):
            total = meta["fields"][field]["count"]
            progress(stage=labels[field], stage_index=stage, current=0, total=total)
            cursor = source_con.execute(dimensions.record_sql(field), [name])
            columns = [column[0] for column in cursor.description]
            count = 0
            while True:
                progress(stage=labels[field], stage_index=stage, current=count, total=total)
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                batch = []
                for row in rows:
                    item = dict(zip(columns, row))
                    searchable = " ".join(str(item.get(k) or "") for k in ("name", "parent", "component")).lower()
                    batch.append((field, item["position"], json.dumps(item, ensure_ascii=False),
                                  item.get("name"), item.get("parent"), item.get("component"), searchable))
                target.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?)", batch)
                count += len(rows)
                if destination.stat().st_size > CACHE_BYTES:
                    raise ValueError("Dimension index exceeds cache capacity")
            if count != total:
                raise ValueError("Dimension record count changed")
        progress(stage="保存检索索引", stage_index=6, current=0, total=None)
        target.execute("CREATE INDEX by_name ON items(field,name)")
        for column in ("parent", "component"):
            progress(stage="保存检索索引", stage_index=6, current=0, total=None)
            target.execute(f"CREATE INDEX by_{column} ON items(field,{column}) WHERE field='edges'")
        target.commit()
        target.close(); target = None
        if not source_valid():
            raise ValueError("Source changed")
        header.write_text(json.dumps({"version": VERSION, "source": source, "dimension": meta}, ensure_ascii=False), encoding="utf-8")
        return ResultArtifact(header, destination, owner)
    except BaseException:
        if target is not None:
            target.close()
        owner.cleanup()
        raise
    finally:
        if source_con is not None:
            source_con.close()


def submit(settings, name, source, meta, source_valid):
    # TaskManager caches artifacts as a pair. A lost/corrupt derived pair is rebuildable.
    jobs = manager(settings)
    with _lock:
        active = jobs.active(key(name), source=source)
        if active:
            return active
        header = path(settings, name, source)
        if header.exists() and cached(settings, name, source) is None:
            header.unlink(missing_ok=True)
            index_path(header).unlink(missing_ok=True)
        return jobs.submit(key(name), lambda progress: build(
            settings, name, source, meta, progress, source_valid), source=source)


def records(header, field, *, keyword="", page=1, element="", index=None):
    if field not in dimensions.FIELDS:
        raise ValueError("Unknown dimension field")
    clauses, args = ["field=?"], [field]
    if keyword.strip():
        clauses.append("instr(search,?)>0"); args.append(keyword.strip().lower())
    if field == "edges" and element:
        clauses.append("(parent=? OR component=?)"); args.extend([element, element])
    if index is not None:
        clauses.append("position=?"); args.append(index)
    where = " AND ".join(clauses)
    with closing(sqlite3.connect(index_path(header).resolve().as_uri() + "?mode=ro", uri=True)) as con:
        total = con.execute("SELECT count(*) FROM items WHERE " + where, args).fetchone()[0]
        pages = max(1, (total + 49) // 50)
        page = max(1, min(page, pages))
        items = [json.loads(row[0]) for row in con.execute("SELECT payload FROM items WHERE " + where +
            " ORDER BY position LIMIT 50 OFFSET ?", args + [(page - 1) * 50])]
        present = set()
        if field == "edges":
            names = sorted({v for item in items for v in (item["parent"], item["component"]) if v})
            if names:
                present = {row[0] for row in con.execute("SELECT name FROM items WHERE field='elements' AND name IN (" +
                    ",".join("?" for _ in names) + ")", names)}
        dimensions.decorate(items, field, present)
    return dict(items=items, total=total, pages=pages, page=page, limit=50,
                start=(page - 1) * 50 + 1 if total else 0, end=min(page * 50, total))
