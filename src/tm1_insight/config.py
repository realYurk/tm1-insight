"""统一配置：单一配置源，消除散落的硬编码路径与明文凭据。

优先级：环境变量 > .env 文件 > 默认值。
用法：
    from tm1_insight.config import get_settings
    cfg = get_settings()
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _app_root() -> Path:
    """程序目录（Application Directory，只读，不含用户数据）。

    源码运行：TM1 Insight/ 根目录。
    PyInstaller 打包（sys.frozen）：exe 所在目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _user_data_root() -> Path:
    """用户数据目录（User Data Directory，可写）。

    Portable 产品原则：软件与数据彻底分离。

    优先顺序：
      1. 环境变量 TM1_INSIGHT_HOME（用户显式指定）
      2. 源码开发模式 -> 项目根目录（保持历史行为，data/.env 在项目下）
      3. Portable 打包模式（sys.frozen）-> %LOCALAPPDATA%\\TM1 Insight\\

    这样 Portable 版即使放在 C:\\Program Files\\ 或只读 U 盘也能运行：
    config / data / logs 全部写到用户自己的 LOCALAPPDATA，无需管理员权限。
    """
    env_home = os.environ.get("TM1_INSIGHT_HOME")
    if env_home:
        return Path(env_home).resolve()

    if not getattr(sys, "frozen", False):
        # 源码开发：沿用项目根目录，保持现有测试/开发行为不变
        return _app_root()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "TM1 Insight"
    # LOCALAPPDATA 不可用时退化为用户主目录
    return Path.home() / ".tm1-insight"


# 程序目录（只读，代码/资源/默认配置所在）
_PROJECT_ROOT = _app_root()

# 用户数据目录（可写，.env / data / logs 所在）
_USER_DATA_ROOT = _user_data_root()

# 数据目录覆盖（Task 19：Import Local Data 用）。
# 用户通过 UI 选择本地数据目录后，这里记录绝对路径；Store 连接时优先使用它。
# 用环境变量 TM1_INSIGHT_DATA_DIR 或 set_data_dir() 设置。
_DATA_DIR_OVERRIDE: Path | None = None
_source_selection_lock = threading.RLock()

def _data_dir_state_path() -> Path:
    return _USER_DATA_ROOT / "data_dir_override.txt"

try:
    _saved_data_dir = _data_dir_state_path().read_text(encoding="utf-8").strip()
    if _saved_data_dir:
        _DATA_DIR_OVERRIDE = Path(_saved_data_dir).resolve()
except OSError:
    pass


def set_data_dir(path: str | Path | None) -> None:
    with _source_selection_lock:
        _persist_data_dir(path)


def activate_collected_source(path: Path, expected_db: Path) -> None:
    """Atomically avoid replacing a source the user selected during collection."""
    with _source_selection_lock:
        if get_settings().db_path.resolve() != expected_db.resolve():
            raise ValueError("Source changed during collection")
        _persist_data_dir(path)


def _persist_data_dir(path: str | Path | None) -> None:
    """设置数据目录覆盖（切换数据源）。None 表示清除覆盖、回到默认。"""
    global _DATA_DIR_OVERRIDE
    candidate = Path(path).resolve() if path else None
    state = _data_dir_state_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    if candidate is None:
        state.unlink(missing_ok=True)
    else:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=state.parent,
                                         prefix=".source-", suffix=".tmp", delete=False) as stream:
            stream.write(str(candidate))
            temporary = Path(stream.name)
        try:
            os.replace(temporary, state)
        finally:
            temporary.unlink(missing_ok=True)
    # Only change the live configuration after persistence has succeeded.
    _DATA_DIR_OVERRIDE = candidate
    get_settings.cache_clear()


def get_data_dir_override() -> Path | None:
    """返回当前数据目录覆盖（无覆盖时为 None）。"""
    return _DATA_DIR_OVERRIDE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_USER_DATA_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- TM1 连接 ----
    tm1_address: str = ""      # 必填：通过 .env / 环境变量提供
    tm1_port: int = 0          # 必填：通过 .env / 环境变量提供
    tm1_user: str = ""         # 必填：通过 .env / 环境变量提供
    tm1_password: str = ""     # 必填：通过 .env / 环境变量提供，绝不明文写死
    tm1_ssl: bool = False
    tm1_namespace: str = ""    # 可选：CAM 命名空间，按环境填写
    tm1_ca_bundle: Path | None = None  # Metadata recovery: trusted PEM CA; verification cannot be disabled

    # ---- 采集 ----
    tm1_max_workers: int = 8
    tm1_skip_existing: bool = True
    tm1_light_system_dims: bool = True

    # ---- 本地数据目录 ----
    data_dir: Path = Field(default=Path("./data"))
    database_file: Path | None = None
    input_applications_dir: Path = Field(default=Path("./data/inputs/applications"))
    input_externals_dir: Path = Field(default=Path("./data/inputs/externals"))
    input_process_dir: Path = Field(default=Path("./data/inputs/process"))
    input_rux_dir: Path = Field(default=Path("./data/inputs/rux"))

    # ---- Web 服务 ----
    web_host: str = "127.0.0.1"
    web_port: int = 8000

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        """把相对路径解析为基于「用户数据目录」的绝对路径。

        源码开发：用户数据目录 == 项目根，行为不变。
        Portable：用户数据目录 == %LOCALAPPDATA%\\TM1 Insight\\，与程序目录分离。

        数据目录覆盖（Task 19 Import Local Data）：若用户通过 UI 选择了
        本地数据目录（set_data_dir），data_dir 优先指向它，其余 input_* 仍
        跟随默认用户数据目录。
        """
        # 数据目录覆盖优先级最高（用户主动选择的数据目录）
        if _DATA_DIR_OVERRIDE is not None:
            if _DATA_DIR_OVERRIDE.suffix.lower() == ".duckdb":
                self.database_file = _DATA_DIR_OVERRIDE
                parent = _DATA_DIR_OVERRIDE.parent
                self.data_dir = parent.parent if parent.name.lower() == "db" else parent
            else:
                self.data_dir = _DATA_DIR_OVERRIDE
                self.database_file = None

        for name in (
            "data_dir",
            "input_applications_dir",
            "input_externals_dir",
            "input_process_dir",
            "input_rux_dir",
        ):
            p = Path(getattr(self, name))
            if not p.is_absolute():
                setattr(self, name, (_USER_DATA_ROOT / p).resolve())
        return self

    # ---- 派生路径 ----
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.database_file or self.db_dir / "tm1_insight.duckdb"

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def user_data_root(self) -> Path:
        """用户数据目录（config / data / logs 根）。"""
        return _USER_DATA_ROOT

    @property
    def logs_dir(self) -> Path:
        """日志目录（用户数据目录下）。"""
        return _USER_DATA_ROOT / "logs"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.raw_dir,
            self.parquet_dir,
            self.db_dir,
            self.input_applications_dir,
            self.input_externals_dir,
            self.input_process_dir,
            self.input_rux_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
