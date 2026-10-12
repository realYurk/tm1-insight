"""Local process isolation for CPU work; no network or customer source output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def isolated_report(settings, query, progress):
    # A frozen application needs its own executable worker entry point. Source
    # installations use an independent interpreter to avoid UI GIL contention.
    if getattr(sys, "frozen", False):
        from tm1_insight.learning.engine import build_report
        from tm1_insight.store.db import Store
        con=Store(settings).connect(read_only=True)
        try:return build_report(con,query,progress)
        finally:con.close()
    root=settings.user_data_root / "cache" / "learning-workers"
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        result=Path(folder) / "result.json"
        environment=os.environ.copy()
        source_root=str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"]=source_root + os.pathsep + environment.get("PYTHONPATH", "")
        child=subprocess.Popen([sys.executable,"-m","tm1_insight.learning.worker",str(settings.db_path),query,str(result)],
                               stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",
                               env=environment,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            for line in child.stdout:
                progress(**json.loads(line))
            if child.wait()!=0 or not result.exists():
                raise RuntimeError("本地学习进程未能完成，请重新分析。")
            return json.loads(result.read_text(encoding="utf-8"))
        finally:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            child.stdout.close()


def main():
    from tm1_insight.config import Settings
    from tm1_insight.learning.engine import build_report
    from tm1_insight.store.db import Store
    database,query,destination=sys.argv[1:]
    settings=Settings().model_copy(update={"database_file":Path(database),"data_dir":Path(database).parent})
    def progress(**event):
        print(json.dumps(event,ensure_ascii=True),flush=True)
    con=Store(settings).connect(read_only=True)
    try:report=build_report(con,query,progress)
    finally:con.close()
    Path(destination).write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")


if __name__=="__main__":main()
