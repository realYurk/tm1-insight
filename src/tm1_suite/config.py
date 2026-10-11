"""统一配置：单一配置源，消除散落的硬编码路径与明文凭据。

优先级：环境变量 > .env 文件 > 默认值。
用法：
    from tm1_suite.config import get_settings
    cfg = get_settings()
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    """项目根目录。

    打包成 exe 时（sys.frozen），数据目录应放在 exe 同级（可持久化），
    由 run_app.py 通过 DATA_DIR 环境变量传入；源码运行时用 parents[2] 定位。
    """
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env).resolve()
    if getattr(sys, "frozen", False):
        # 兜底：exe 同级目录
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


# 项目根目录（tm1-suite/），与 .env 所在位置一致
_PROJECT_ROOT = _project_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
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

    # ---- 采集 ----
    tm1_max_workers: int = 8
    tm1_skip_existing: bool = True
    tm1_light_system_dims: bool = True

    # ---- 本地数据目录 ----
    data_dir: Path = Field(default=Path("./data"))
    input_applications_dir: Path = Field(default=Path("./data/inputs/applications"))
    input_externals_dir: Path = Field(default=Path("./data/inputs/externals"))
    input_process_dir: Path = Field(default=Path("./data/inputs/process"))
    input_rux_dir: Path = Field(default=Path("./data/inputs/rux"))

    # ---- Web 服务 ----
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        """把相对路径解析为基于项目根目录的绝对路径。"""
        for name in (
            "data_dir",
            "input_applications_dir",
            "input_externals_dir",
            "input_process_dir",
            "input_rux_dir",
        ):
            p = Path(getattr(self, name))
            if not p.is_absolute():
                setattr(self, name, (_PROJECT_ROOT / p).resolve())
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
        return self.db_dir / "tm1_suite.duckdb"

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

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
