"""Build a fresh, program-only local release. Never deletes previous releases."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    output=ROOT/"release"/("portable-"+stamp)
    output.mkdir(parents=True,exist_ok=False)
    def source_hashes():
        files=[p for p in (ROOT/"src"/"tm1_insight").rglob("*") if p.is_file() and p.suffix in {".py",".html",".css",".js",".svg",".txt"}]
        files += [ROOT/"launcher.py",ROOT/"tm1_insight.spec",ROOT/"PORTABLE_README.txt",ROOT/"requirements-build.lock"]
        return {str(p.relative_to(ROOT)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
    initial_hashes=source_hashes()
    environment=os.environ.copy()
    environment["PYTHONNOUSERSITE"]="1"
    subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean",
                    "--distpath",str(output/"dist"),"--workpath",str(output/"work"),str(ROOT/"tm1_insight.spec")],
                   cwd=ROOT,env=environment,check=True)
    if initial_hashes!=source_hashes():raise RuntimeError("Source changed during build; rebuild before delivery")
    program=output/"dist"/"TM1 Insight"
    shutil.copyfile(ROOT/"PORTABLE_README.txt",program/"README.txt")
    shutil.copyfile(ROOT/"LICENSE",program/"LICENSE.txt")
    lock=ROOT/"requirements-build.lock"
    if lock.exists():shutil.copyfile(lock,program/"runtime-lock.txt")
    forbidden={".env","data_dir_override.txt","last_local_source.txt","reviews.sqlite3"}
    for file in program.rglob("*"):
        if file.is_file() and (file.name in forbidden or file.suffix.lower() in {".duckdb",".parquet"}):
            raise RuntimeError("Release audit rejected a private data file")
    manifest={"built_at":stamp,"contains_customer_data":False,"source_hashes":initial_hashes,"files":{
        str(file.relative_to(program)).replace("\\","/"):hashlib.sha256(file.read_bytes()).hexdigest()
        for file in program.rglob("*") if file.is_file()}}
    (program/"BUILD_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"release"/"latest-build.txt").write_text(str(program),encoding="utf-8")
    print("Program-only local build:",program)


if __name__=="__main__":main()
