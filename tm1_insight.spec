# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：把 TM1 Insight 打包成 Windows Portable 目录（onedir）。

产物名 "TM1 Insight"（可执行文件 "TM1 Insight.exe"）。
软件与数据分离：只打包程序/资源/依赖，绝不打包真实 data/。
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # 项目根（spec 所在目录）
SRC = ROOT / "src"

# 要收集的数据文件：templates + static（含 icons），保持包内相对结构
datas = [
    (str(SRC / "tm1_insight" / "api" / "templates"), "tm1_insight/api/templates"),
    (str(SRC / "tm1_insight" / "api" / "static"), "tm1_insight/api/static"),
]

# 字符串导入（uvicorn.run("tm1_insight.api.app:app")）不会自动收集，需显式列出
hiddenimports = [
    "tm1_insight",
    "tm1_insight.cli",
    "tm1_insight.config",
    "tm1_insight.portable",
    "tm1_insight.datasource",
    "tm1_insight.api",
    "tm1_insight.api.app",
    "tm1_insight.api.experience",
    "tm1_insight.learning.worker",
    "tm1_insight.store",
    "tm1_insight.store.db",
    "tm1_insight.store.queries",
    "tm1_insight.store.graph_adapter",
    "tm1_insight.lineage.engine",
    "tm1_insight.impact.engine",
    "tm1_insight.compare.engine",
    "tm1_insight.health.engine",
    "tm1_insight.change_intelligence.engine",
    "tm1_insight.ingest.exporter",
    "tm1_insight.ingest.loader",
    "tm1_insight.ingest.audit",
    "tm1_insight.tm1.client",
]

# conda 环境的运行时 DLL（PyInstaller 默认不收集，会导致 _ctypes/_ssl/_lzma/_sqlite3 等
# 报 "DLL load failed"）。conda 的 DLL 命名不规范（libssl-3-x64.dll 而非 libssl.dll），
# PyInstaller 按标准名找不到，因此这里显式打包 Library/bin/ 里的全部运行时 DLL。
# 注意 sys.executable 的 dirname 只取一层（conda 的 python.exe 就在 anaconda/ 根，无 bin 中间层）。
_conda_root = sys.base_prefix  # Works for an isolated venv on a conda Python.
_library_bin = os.path.join(_conda_root, "Library", "bin")

# 需要打包的 DLL（覆盖 Python 标准库扩展 + 第三方 C 库的运行时依赖）
_missing_dlls = [
    # Python 标准库扩展依赖
    "ffi.dll",              # _ctypes
    "liblzma.dll",          # _lzma
    "libbz2.dll",           # _bz2
    "libmpdec-4.dll",       # _decimal
    "libexpat.dll",         # pyexpat / _elementtree
    "sqlite3.dll",          # _sqlite3
    "libssl-3-x64.dll",     # _ssl（OpenSSL）
    "libcrypto-3-x64.dll",  # _ssl（OpenSSL）
    # 常见第三方 C 库依赖（TM1py 的 requests/urllib3 等可能用到）
    "zlib.dll",             # zlib
    "liblz4.dll",           # lz4（duckdb 可能依赖）
    "libzstd.dll",          # zstd
    "zstd.dll",             # zstd（另一命名）
    "libcurl.dll",          # curl（TM1py HTTP 连接）
    "libssh2.dll",          # ssh2（libcurl 依赖）
    "libxml2.dll",          # xml（lxml/openpyxl 可能依赖）
    "iconv.dll",            # iconv（libxml2 依赖）
    "charset.dll",          # libxml2 依赖
    "bzip2.dll",            # bzip2（另一命名）
    # MSVC 运行时（保证目标机即使没有 VC++ redistributable 也能跑）
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "concrt140.dll",
    "vcomp140.dll",
    "ucrtbase.dll",
]
_binaries = []
for _dll in _missing_dlls:
    _p = os.path.join(_library_bin, _dll)
    if os.path.exists(_p):
        _binaries.append((_p, "."))
    else:
        print(f"[spec] WARNING: DLL not found, skipped: {_dll}")

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(SRC)],
    binaries=_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "tkinter", "pyarrow.tests", "pyarrow.testing", "numpy.tests"],
    noarchive=False,
)

# Dependency hooks may collect upstream fixtures even when test modules are
# excluded. Filter them from the program manifest before COLLECT.
a.datas = [entry for entry in a.datas if not any(part.lower() in {"tests", "testing"} for part in Path(entry[0]).parts)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TM1 Insight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留控制台，方便看启动日志/错误
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TM1 Insight",
)
