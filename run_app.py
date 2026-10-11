"""tm1-suite 独立可执行程序入口（PyInstaller 打包用）。

双击生成的 exe 时执行：
1. 检测本地是否有数据，没有则自动生成演示数据
2. 自动打开浏览器
3. 启动 Web UI

数据目录固定在 exe 同级的 data/ 下，用户数据可持久化、可替换。
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path


def _exe_dir() -> Path:
    """exe 所在目录（用户双击的位置），数据目录放在这里。

    打包成 exe 时用 sys.executable；源码运行时用脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _ensure_data_dir(exe_dir: Path) -> None:
    """把数据目录固定到 exe 同级，并写入 .env 让配置生效。"""
    data_dir = exe_dir / "data"
    data_dir.mkdir(exist_ok=True)
    # 通过环境变量把数据目录传进去，避免依赖 .env 文件
    os.environ.setdefault("DATA_DIR", str(data_dir))


def _ensure_demo_data() -> None:
    """若无本地数据，生成演示数据。"""
    from tm1_suite.config import get_settings
    from tm1_suite.store.db import Store

    settings = get_settings()
    if settings.db_path.exists():
        return
    from tm1_suite import seed_demo

    print("[tm1-suite] 未检测到本地数据，正在生成演示数据（无需连 TM1）...")
    seed_demo.seed(settings)
    print("[tm1-suite] 演示数据已就绪。")


def main() -> None:
    exe_dir = _exe_dir()
    os.chdir(exe_dir)  # 确保相对路径解析正确
    _ensure_data_dir(exe_dir)

    # 延迟导入：让 PyInstaller 能正确收集 tm1_suite 依赖
    from tm1_suite.config import get_settings

    settings = get_settings()
    host = settings.web_host
    port = settings.web_port
    url = f"http://localhost:{port}"

    _ensure_demo_data()

    # 启动后 1.5 秒自动打开浏览器（给 uvicorn 一点启动时间）
    def _open_browser() -> None:
        import time

        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"[tm1-suite] 正在启动，浏览器将自动打开 {url}")
    print("[tm1-suite] 关闭本窗口即停止服务。")

    import uvicorn
    from tm1_suite.api.app import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
