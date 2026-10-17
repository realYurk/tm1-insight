"""Python 版本兼容性检查脚本（供另一台电脑直接运行，无需安装任何依赖）。

用法（在报错机器上执行）：
    python scripts/check_python_compat.py

输出：解释器路径、Python 版本、是否满足 TM1 Insight 最低要求，
以及针对性的中文建议。脚本本身只用标准库，可在 Python 3.6+ 解析。
"""
import platform
import sys

MIN_MAJOR, MIN_MINOR = 3, 9


def main() -> int:
    print("=" * 60)
    print("TM1 Insight — Python 版本兼容性检查")
    print("=" * 60)
    print(f"  解释器路径:  {sys.executable}")
    print(f"  Python 版本: {platform.python_version()} ({platform.python_implementation()})")
    print(f"  实现详情:    {sys.version}")

    vi = sys.version_info
    ok = (vi.major, vi.minor) >= (MIN_MAJOR, MIN_MINOR)

    print("-" * 60)
    if ok:
        print("[通过] Python 版本满足 TM1 Insight 最低要求（>= 3.9）。")
        if (vi.major, vi.minor) < (3, 11):
            print("[提示] 当前为 Python 3.9/3.10，安装依赖时会自动解析到")
            print("       3.9 兼容版本（依赖声明已加版本上限）。")
        return 0

    print(f"[失败] Python {vi.major}.{vi.minor} 低于最低支持版本 3.9。")
    print("TM1 Insight 源码运行要求 Python >= 3.9。")
    print("请安装 Python 3.9 或更高版本后重试：")
    print("    https://www.python.org/downloads/")
    print("（本项目不会自动升级或修改系统 Python，请自行安装。）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
