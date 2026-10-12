"""Local process isolation for CPU work; no network or customer source output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def isolated_export(settings, report_path):
    """Compress a private report outside the Web process; caller owns cleanup."""
    root=settings.user_data_root / "cache" / "learning-workers"
    root.mkdir(parents=True,exist_ok=True)
    temporary=tempfile.TemporaryDirectory(dir=root)
    destination=Path(temporary.name)/"TM1_Study.zip"
    command=[sys.executable,"--internal-learning-worker"] if getattr(sys,"frozen",False) else [sys.executable,"-m","tm1_insight.learning.worker"]
    command += ["--export",str(report_path),str(destination),str(os.getpid())]
    environment=os.environ.copy()
    environment["PYTHONPATH"]=str(Path(__file__).resolve().parents[2])+os.pathsep+environment.get("PYTHONPATH","")
    try:
        subprocess.run(command,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),check=True,timeout=300)
        return destination,temporary
    except BaseException:
        temporary.cleanup()
        raise


def isolated_report(settings, query, progress, *, as_artifact=False, source=None):
    root=settings.user_data_root / "cache" / "learning-workers"
    root.mkdir(parents=True,exist_ok=True)
    temporary=tempfile.TemporaryDirectory(dir=root)
    transferred=False
    try:
        result=Path(temporary.name) / "result.json"
        environment=os.environ.copy()
        source_root=str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"]=source_root + os.pathsep + environment.get("PYTHONPATH", "")
        command=[sys.executable,"--internal-learning-worker"] if getattr(sys,"frozen",False) else [sys.executable,"-m","tm1_insight.learning.worker"]
        command += [str(settings.db_path),query,str(result),str(os.getpid()),str(settings.data_dir),source or "","indexed" if as_artifact else "json"]
        child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",
                               env=environment,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            for line in child.stdout:progress(**json.loads(line))
            if child.wait()!=0 or not result.exists():raise RuntimeError("本地学习进程未能完成，请重新分析。")
            if as_artifact:
                from tm1_insight.tasks import ResultArtifact
                from tm1_insight.learning.pages import index_path
                transferred=True
                return ResultArtifact(result,index_path(result),temporary)
            return json.loads(result.read_text(encoding="utf-8"))
        finally:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            child.stdout.close()
    finally:
        if not transferred:temporary.cleanup()


def watch_parent(pid):
    """Stop if the UI process exits, including closing a Windows console."""
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:os._exit(3)
        try:
            if kernel.WaitForSingleObject(handle,0xFFFFFFFF)==0:os._exit(3)
        finally:kernel.CloseHandle(handle)
    else:
        import time
        while os.getppid()==pid:time.sleep(1)
        os._exit(3)


def main(argv=None):
    from tm1_insight.config import Settings
    from tm1_insight.learning.engine import build_report
    from tm1_insight.store.db import Store
    arguments=sys.argv[1:] if argv is None else argv
    if arguments[0]=="--export":
        import zipfile
        from tm1_insight.learning.engine import markdown,VERSION
        _,source,destination,parent=arguments
        threading.Thread(target=watch_parent,args=(int(parent),),daemon=True).start()
        report=json.loads(Path(source).read_text(encoding="utf-8"))
        if report.get("version")!=VERSION:raise ValueError("Not a current study report")
        with zipfile.ZipFile(destination,"w",zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("READ_ME_FIRST.md",markdown(report))
            archive.write(source,"study.json")
            archive.writestr("PRIVACY.txt","Private customer/model knowledge. Publication is not authorized.\n")
        return
    database,query,destination=arguments[:3]
    if len(arguments)>3:threading.Thread(target=watch_parent,args=(int(arguments[3]),),daemon=True).start()
    settings=Settings().model_copy(update={"database_file":Path(database),"data_dir":Path(arguments[4]) if len(arguments)>4 else Path(database).parent})
    def progress(**event):
        print(json.dumps(event,ensure_ascii=True),flush=True)
    con=Store(settings).connect(read_only=True)
    try:report=build_report(con,query,progress)
    finally:con.close()
    if len(arguments)>5 and arguments[5]:report["source_fingerprint"]=arguments[5]
    with Path(destination).open("w",encoding="utf-8") as stream:json.dump(report,stream,ensure_ascii=False)
    if len(arguments)>6 and arguments[6]=="indexed":
        progress(stage="建立分页检索索引",stage_index=6,stages_total=6,current=0,total=None)
        from tm1_insight.learning.pages import build
        build(Path(destination),report)


if __name__=="__main__":main()
