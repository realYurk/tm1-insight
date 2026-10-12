"""TM1 Insight Portable 启动入口。

双击 exe 直接启动 Web UI，是 PyInstaller 打包的入口脚本。

行为：
    双击 exe（无参数）           -> 启动 Web UI，自动开浏览器
    TM1 Insight.exe web          -> 同上
    TM1 Insight.exe <cli 命令>   -> 转发到 CLI（status/query/ingest/...）

设计原则（Task 18 Portable Productization）：
    - 端口被占用时自动递增（8000 -> 8001 -> 8002 ...）
    - 等待服务 ready 后自动打开默认浏览器
    - 日志写入用户数据目录 logs/（软件与数据分离）
    - 只管理本进程启动的 Web Server，关闭窗口即停止，不留孤儿进程
"""
from __future__ import annotations

import logging
import sys

import uvicorn

from tm1_insight.cli import app as cli_app
from tm1_insight.config import get_settings
from tm1_insight.portable import pick_port, start_browser_thread

logger = logging.getLogger("tm1-insight.launcher")


def _setup_file_logging(settings) -> None:
    """把日志追加写入用户数据目录 logs/launcher.log。"""
    try:
        log_dir = settings.logs_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "launcher.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.getLogger().addHandler(fh)
    except OSError:
        pass  # 日志目录不可写时退化为仅控制台


def _run_web() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    _setup_file_logging(settings)

    port = pick_port(settings.web_host, settings.web_port)
    if port != settings.web_port:
        logger.info("Port %d in use, using %d instead.", settings.web_port, port)

    url = f"http://127.0.0.1:{port}"
    print("[TM1 Insight] Starting Web UI...")
    print(f"[TM1 Insight] URL:       {url}")
    print(f"[TM1 Insight] Data dir:  {settings.data_dir}")
    print(f"[TM1 Insight] Log dir:   {settings.logs_dir}")
    print("[TM1 Insight] Opening browser automatically...")
    print("[TM1 Insight] Close this window (or press Ctrl+C) to stop.")

    start_browser_thread(port)

    try:
        uvicorn.run(
            "tm1_insight.api.app:app",
            host=settings.web_host,
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    finally:
        logger.info("Web server stopped.")


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0]=="--internal-learning-worker":
        from tm1_insight.learning.worker import main as worker_main
        worker_main(argv[1:])
        return
    if argv and argv[0]=="--self-check":
        import json,sqlite3,ssl,lzma,ctypes
        import duckdb,openpyxl,pyarrow,TM1py
        from tm1_insight.api.app import app
        from tm1_insight import __version__
        con=duckdb.connect(":memory:");assert con.execute("SELECT 1").fetchone()[0]==1;con.close()
        con=sqlite3.connect(":memory:");assert con.execute("SELECT 1").fetchone()[0]==1;con.close()
        print(json.dumps({"status":"ok","version":__version__,"routes":len(app.routes)},ensure_ascii=True))
        return
    if not argv:
        _run_web()
        return
    if argv[0] == "web" and len(argv)==1:
        _run_web()
        return
    cli_app()


if __name__ == "__main__":
    main()
