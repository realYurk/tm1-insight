"""采集对象的本地文件命名与 manifest 管理。

解决 Windows MAX_PATH（260 字符）限制下，长名称 TM1 对象导出失败的问题。

设计原则：
- 短名确定性：``sha256(原始名称)`` 前 16 位 hex，相同名称每次得到相同短名。
- 只在完整路径可能超限时启用短名；普通名称保持原名，人类可读、向后兼容。
- 原始名称始终完整保留在 JSON 内容（``name`` 字段）与 manifest 中，不截断业务名称。
- manifest 文件名以 ``_`` 开头，loader 已用 ``startswith("_")`` 跳过，不会被误当普通对象。
- 旧版原始长名文件（历史导出）无需迁移，loader 读取 JSON 内容，天然兼容。

不依赖用户修改注册表 / 环境变量 / 管理员权限，纯代码级兼容。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from tm1_insight.tm1.client import safe_filename

logger = logging.getLogger(__name__)

# 完整路径安全阈值：Windows MAX_PATH=260，留 20 字符缓冲。
MAX_PATH_SAFE = 240

# 各对象类型的短名前缀（同时用作 manifest 的 type 标记）。
TYPE_PREFIX = {
    "cubes": "c",
    "processes": "p",
    "dimensions": "d",
    "chores": "ch",
    "security": "s",
}

# manifest 文件名（``_`` 前缀，loader 会跳过）。
MANIFEST_NAME = "_manifest.json"

# 保护 manifest 读写的锁（exporter 多线程写入短名时需要）。
_manifest_lock = threading.Lock()


def short_stem(name: str, obj_type: str) -> str:
    """生成确定性的短文件名主干（不含 .json 后缀）。

    使用 sha256 前 16 位 hex（64 bit），相同名称稳定映射到相同短名。
    """
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    prefix = TYPE_PREFIX.get(obj_type, "x")
    return f"{prefix}_{digest}"


def resolve_object_path(raw_dir: Path, obj_type: str, name: str) -> tuple[Path, bool]:
    """返回 (目标文件路径, 是否使用短名)。

    - 若完整路径长度 <= MAX_PATH_SAFE，使用原名（safe_filename 处理非法字符）。
    - 否则使用确定性短名，避免 Windows MAX_PATH 超限。
    """
    plain_path = raw_dir / obj_type / f"{safe_filename(name)}.json"
    if len(str(plain_path)) <= MAX_PATH_SAFE:
        return plain_path, False
    short_path = raw_dir / obj_type / f"{short_stem(name, obj_type)}.json"
    return short_path, True


class Manifest:
    """对象名称 <-> 短文件名的映射索引。

    只在对象使用短名时记录条目；普通名称对象不写入 manifest。
    用于：冲突检测、人类排查、未来反向查找。
    """

    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
        self._entries: dict[str, str] = {}  # 原始名称 -> 短文件名主干
        self._by_stem: dict[str, str] = {}  # 短文件名主干 -> 原始名称（冲突检测）

    def register(self, name: str, obj_type: str, used_short: bool) -> str:
        """登记一个对象；返回实际使用的文件名主干。

        若发现哈希冲突（不同名称映射到同一短名），抛出 RuntimeError，绝不静默覆盖。
        """
        if not used_short:
            return safe_filename(name)
        stem = short_stem(name, obj_type)
        existing = self._by_stem.get(stem)
        if existing is not None and existing != name:
            raise RuntimeError(
                f"短名哈希冲突: {name!r} 与 {existing!r} 都映射到 {stem}"
            )
        self._by_stem[stem] = name
        self._entries[name] = stem
        return stem

    def to_dict(self) -> dict:
        return {"entries": self._entries}

    def save(self) -> None:
        """写 manifest 到 raw_dir/_manifest.json（线程安全）。"""
        path = self.raw_dir / MANIFEST_NAME
        with _manifest_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, raw_dir: Path) -> "Manifest":
        """读取已有 manifest（不存在则返回空 manifest）。"""
        m = cls(raw_dir)
        path = raw_dir / MANIFEST_NAME
        if not path.exists():
            return m
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("读取 manifest 失败（忽略）: %s", e)
            return m
        for name, stem in (data.get("entries") or {}).items():
            m._entries[name] = stem
            m._by_stem[stem] = name
        return m
