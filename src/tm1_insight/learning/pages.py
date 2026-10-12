"""Rebuildable SQLite paging index for private JSON reports (stdlib only).

The original model remains DuckDB. This disposable index avoids decoding a
whole-model report for every page, search or contract lookup.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing

SECTIONS={"chapters","processes","cubes","findings","duplicate_groups","dimensions","rules","chores","coupling"}


def index_path(path):return Path(path).with_suffix(".pages.sqlite3")


def connect(path):
    return sqlite3.connect(index_path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=1)


def valid(path):
    if not index_path(path).exists():return False
    try:
        with closing(connect(path)) as con:
            info=json.loads(con.execute("SELECT payload FROM meta WHERE key='file'").fetchone()[0])
        stat=Path(path).stat()
        return info==[stat.st_size,stat.st_mtime_ns]
    except (OSError,sqlite3.Error,ValueError,TypeError):return False


def build(path,report):
    destination=index_path(path);temporary=destination.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    con=sqlite3.connect(temporary)
    try:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,payload TEXT)")
        con.execute("CREATE TABLE items(section TEXT,position INTEGER,payload TEXT,search TEXT,patterns TEXT,PRIMARY KEY(section,position))")
        header={key:value for key,value in report.items() if key not in SECTIONS}
        stat=Path(path).stat()
        con.executemany("INSERT INTO meta VALUES (?,?)",[("header",json.dumps(header,ensure_ascii=False)),("file",json.dumps([stat.st_size,stat.st_mtime_ns]))])
        for section in SECTIONS:
            rows=[]
            for position,item in enumerate(report.get(section,[])):
                search=str(item.get("process",item.get("cube",item.get("dimension",item.get("chore",item.get("title",item.get("processes",""))))))).casefold()
                patterns="|"+"|".join(item.get("patterns",{}))+"|"
                rows.append((section,position,json.dumps(item,ensure_ascii=False),search,patterns))
                if len(rows)==128:con.executemany("INSERT INTO items VALUES (?,?,?,?,?)",rows);rows=[]
            if rows:con.executemany("INSERT INTO items VALUES (?,?,?,?,?)",rows)
        con.commit()
    except BaseException:
        con.close();temporary.unlink(missing_ok=True);raise
    finally:con.close()
    try:os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)


def page(path,section,offset,limit,pattern="",q=""):
    if section not in SECTIONS:raise ValueError("未知结果分类。")
    conditions=["section=?"];args=[section]
    if pattern and section=="processes":conditions.append("instr(patterns,?)>0");args.append("|"+pattern+"|")
    if q:conditions.append("instr(search,?)>0");args.append(q.casefold())
    where=" AND ".join(conditions)
    with closing(connect(path)) as con:
        header=json.loads(con.execute("SELECT payload FROM meta WHERE key='header'").fetchone()[0])
        total=con.execute("SELECT count(*) FROM items WHERE "+where,args).fetchone()[0]
        items=[json.loads(row[0]) for row in con.execute("SELECT payload FROM items WHERE "+where+" ORDER BY position LIMIT ? OFFSET ?",args+[limit,offset])]
    return header,total,items


def process(path,name):
    # Exact spelling matters for an evidence identity; search is only a locator.
    with closing(connect(path)) as con:
        items=[json.loads(row[0]) for row in con.execute("SELECT payload FROM items WHERE section='processes' AND search=?",[name.casefold()])]
    return next((item for item in items if item["process"]==name),None)
