"""构建与版本信息（Workbench 1.1 引入）。

供前端展示「当前运行的是哪个版本」，解决用户分不清开发版 / Portable 打包版、
看不到 Git SHA 与构建时间的问题。只暴露非敏感信息，不返回密码 / Token / 完整私有路径。
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from tm1_insight import __version__


def _project_root() -> Path:
    """源码仓库根目录（打包模式下可能不存在，返回 None）。"""
    return Path(__file__).resolve().parent.parent.parent


def _git_short_sha() -> str | None:
    """尝试从 .git 读取当前 HEAD 短 SHA；失败返回 None（不伪造）。"""
    root = _project_root()
    if not (root / ".git").exists():
        return None
    # 优先读 HEAD 文件（无 git 命令依赖）
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1]
            ref_path = root / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:8]
        else:
            return head[:8]
    except Exception:  # noqa: BLE001
        pass
    # 回退到 git 命令
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def _build_time() -> str | None:
    """构建时间。只在打包（Portable）模式下有意义。

    - 打包模式：读 BUILD_MANIFEST.json 里的 built_at 字段，缺失则用 manifest 文件 mtime。
    - 源码模式：返回 None（源码每时每刻都在变，无稳定构建时间，前端显示「未打包」）。
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    manifest = exe_dir / "BUILD_MANIFEST.json"
    if manifest.exists():
        import json as _json
        import datetime as _dt
        try:
            data = _json.loads(manifest.read_text(encoding="utf-8"))
            for key in ("built_at", "build_time", "timestamp"):
                if data.get(key):
                    return str(data[key])
        except Exception:  # noqa: BLE001
            pass
        # 回退：manifest 文件本身的修改时间
        try:
            mtime = manifest.stat().st_mtime
            return _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            pass
    return None


def is_packaged() -> bool:
    """是否为 PyInstaller 打包（Portable）模式。"""
    return bool(getattr(sys, "frozen", False))


@lru_cache(maxsize=1)
def build_info() -> dict:
    """返回展示用版本信息（非敏感）。"""
    return {
        "version": __version__,
        "git_sha": _git_short_sha(),
        "build_time": _build_time(),
        "packaged": is_packaged(),
        "mode": "portable" if is_packaged() else "source",
    }
