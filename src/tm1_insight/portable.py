"""Portable 启动辅助：端口选择、浏览器自动打开、日志。

Task 18 引入，供 CLI `web` 命令与打包入口 launcher.py 复用。
不修改任何核心引擎（parser/resolver/lineage/impact/...）。
"""
from __future__ import annotations

import logging
import socket
import threading
import time
import webbrowser

logger = logging.getLogger("tm1-insight.portable")


def port_in_use(host: str, port: int) -> bool:
    """检测端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def pick_port(host: str, start_port: int, max_tries: int = 100) -> int:
    """从 start_port 开始找第一个可用端口。"""
    for port in range(start_port, start_port + max_tries):
        if not port_in_use(host, port):
            return port
    return start_port  # 极端情况回退，交由 uvicorn 报错


def open_browser_when_ready(port: int, timeout: float = 30.0) -> None:
    """后台线程：轮询直到 Web 服务 ready，然后打开默认浏览器。"""
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                webbrowser.open(url)
                logger.info("Browser opened: %s", url)
                return
        except OSError:
            time.sleep(0.5)
    logger.warning("Web service not ready in %.0fs; browser not opened.", timeout)


def start_browser_thread(port: int) -> threading.Thread:
    """启动一个 daemon 线程，等服务 ready 后自动开浏览器。"""
    t = threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True)
    t.start()
    return t
