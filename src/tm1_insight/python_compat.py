"""Python 版本兼容性检查（Python Compatibility 1.0）。

解决「不同电脑使用不同 Python 版本导致启动失败」的问题：
    1. 报告实际使用的解释器路径、Python 版本、项目版本与 Git 短 SHA。
    2. 在不支持的最低版本下提前退出，并给出清晰的中文错误（而非内部堆栈）。
    3. 供 CLI、launcher、start.bat 与测试统一复用，避免各启动入口策略不一致。

本模块本身必须能在 Python 3.9 上解析：不使用 PEP 604 联合类型，
不依赖任何第三方库，只依赖标准库。
"""
from __future__ import annotations

import platform
import sys

# 本轮兼容性治理确定的最低支持版本（见 docs/PYTHON_COMPATIBILITY_1_0.md）。
MIN_PYTHON = (3, 9)
# 声明支持的版本上限（超出仅警告，不阻断；新版本通常向后兼容）。
RECOMMENDED_PYTHON = (3, 11)

# 已知会导致源码运行失败、且本轮明确不支持的版本下限（低于 MIN_PYTHON 一律拒绝）。
_UNSUPPORTED_HINT = (
    "检测到 Python {actual}，低于最低支持版本 {minimum}。\n"
    "TM1 Insight 源码运行要求 Python >= 3.9（PEP 604 联合类型、内置泛型等）。\n"
    "请安装 Python 3.9 或更高版本后重试：https://www.python.org/downloads/\n"
    "（项目不会自动升级或修改你的系统 Python，请自行安装。）"
)


def version_info() -> dict:
    """返回解释器与项目版本信息（非敏感，供启动横幅与前端展示）。"""
    from tm1_insight import __version__
    from tm1_insight.buildinfo import _git_short_sha

    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_full": sys.version.split()[0],
        "project_version": __version__,
        "git_sha": _git_short_sha(),
    }


def check() -> dict:
    """执行兼容性检查；不满足时抛 SystemExit(1) 并打印中文错误。

    返回 version_info() 的结果，供调用方打印横幅。
    """
    info = version_info()
    actual = sys.version_info[:2]
    if actual < MIN_PYTHON:
        sys.stderr.write(
            _UNSUPPORTED_HINT.format(
                actual=".".join(str(x) for x in actual),
                minimum=".".join(str(x) for x in MIN_PYTHON),
            )
            + "\n"
        )
        raise SystemExit(1)
    return info


def banner() -> str:
    """生成一段可打印的启动横幅，展示解释器路径 / 版本 / 项目版本 / SHA。"""
    info = version_info()
    sha = info["git_sha"] or "unknown"
    lines = [
        "[TM1 Insight] Python 兼容性检查通过",
        f"  Python:      {info['python_full']} ({info['python_implementation']})",
        f"  解释器路径:  {info['python_executable']}",
        f"  项目版本:    {info['project_version']}",
        f"  Git SHA:     {sha}",
    ]
    return "\n".join(lines)
