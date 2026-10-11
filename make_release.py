#!/usr/bin/env python3
"""tm1-suite 发布打包脚本：把项目拆成「程序体」和「数据体」两个 ZIP。

用法（在项目根目录运行）:
    python make_release.py            # 同时生成程序体 + 数据体
    python make_release.py --app-only # 只生成程序体（不含 data/）
    python make_release.py --data-only# 只生成数据体

产物输出到 dist/ 目录:
    tm1-suite-app-<version>.zip    程序体（约 50M，源码 + 启动器 + 依赖清单，更新低频）
    tm1-suite-data-<version>.zip   数据体（约 2G，duckdb + inputs，随 TM1 更新）

设计原则:
  - 程序体与数据体分离，更新数据不用重发程序，反之亦然。
  - 数据体裁掉 data/raw/（1.1G 的断点续传中间产物，用户重新拉取会自动重建）。
  - data/parquet/（98M）保留，供外部分析；也可通过 --no-parquet 裁掉。
"""
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from tm1_suite import __version__

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# 程序体应包含的文件/目录（不含 data/，不含原始工具源码）
APP_INCLUDE = [
    "src",
    "scripts",
    "start.bat",
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    ".env.example",
    "docker-compose.yml",
    "Dockerfile",
    "LICENSE",
]

# 数据体应包含的 data/ 子目录（默认裁掉 raw）
DATA_INCLUDE = ["db", "inputs", "parquet"]


def _zip_dir(zf: zipfile.ZipFile, src: Path, arc_prefix: str = "") -> None:
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src)
            zf.write(p, str(Path(arc_prefix) / rel))


def build_app(version: str) -> Path:
    out = DIST / f"tm1-suite-app-{version}.zip"
    DIST.mkdir(exist_ok=True)
    print(f"[app] 打包程序体 -> {out.name}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in APP_INCLUDE:
            p = ROOT / item
            if not p.exists():
                print(f"      [跳过] {item} 不存在")
                continue
            if p.is_dir():
                _zip_dir(zf, p, item)
            else:
                zf.write(p, item)
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"      完成: {size_mb:.1f} MB")
    return out


def build_data(version: str, no_parquet: bool = False) -> Path:
    out = DIST / f"tm1-suite-data-{version}.zip"
    DIST.mkdir(exist_ok=True)
    data_dir = ROOT / "data"
    print(f"[data] 打包数据体 -> {out.name}（裁掉 raw 中间产物）")
    includes = list(DATA_INCLUDE)
    if no_parquet:
        includes.remove("parquet")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in includes:
            p = data_dir / sub
            if not p.exists():
                print(f"      [跳过] data/{sub} 不存在")
                continue
            _zip_dir(zf, p, f"data/{sub}")
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"      完成: {size_mb:.1f} MB")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="tm1-suite 发布打包")
    parser.add_argument("--app-only", action="store_true", help="只打程序体")
    parser.add_argument("--data-only", action="store_true", help="只打数据体")
    parser.add_argument("--no-parquet", action="store_true", help="数据体不含 parquet/")
    args = parser.parse_args()

    version = __version__ or "0.1.0"
    DIST.mkdir(exist_ok=True)

    if args.data_only:
        build_data(version, args.no_parquet)
    elif args.app_only:
        build_app(version)
    else:
        build_app(version)
        print()
        build_data(version, args.no_parquet)

    print()
    print("打包完成，产物在 dist/ 目录。")
    print("  分发建议：")
    print("  - 新用户：解压程序体 + 数据体到同一目录，双击 start.bat 即可。")
    print("  - 更新数据：只替换数据体（解压覆盖 data/），程序体不动。")
    print("  - 更新程序：只替换程序体（解压覆盖源码），数据体不动。")


if __name__ == "__main__":
    main()
