# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 tm1-suite 打成独立 exe（双击即用，免安装）。

用法（在项目根目录运行）:
    pyinstaller tm1_suite.spec

产物:
    dist/tm1-suite/tm1-suite.exe    独立可执行程序
"""
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821  (SPECPATH 由 PyInstaller 注入)

# 模板 + 静态资源 + 图标，需要作为数据文件打进 exe（运行时解压到 _MEIPASS）
datas = [
    (str(ROOT / "src" / "tm1_suite" / "api" / "templates"), "tm1_suite/api/templates"),
    (str(ROOT / "src" / "tm1_suite" / "api" / "static"), "tm1_suite/api/static"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="tm1-suite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留控制台，便于看启动日志（双击会弹一个黑窗口）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
