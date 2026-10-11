"""CLI 入口（typer）。

命令：
    tm1-suite ingest [--no-export] [--no-drop]   拉取 + 入库
    tm1-suite status                               各表行数
    tm1-suite query <cube>                         查询 Cube 的读写者与维度
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import typer

from tm1_suite.config import get_settings
from tm1_suite.store.db import Store
from tm1_suite.store.queries import cube_summary


def _setup_logging() -> None:
    """配置日志：控制台 + 滚动文件（logs/tm1-suite.log），方便商用排查问题。"""
    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    try:
        fh = RotatingFileHandler(
            log_dir / "tm1-suite.log",
            maxBytes=5 * 1024 * 1024,  # 5MB 一个文件
            backupCount=3,
            encoding="utf-8",
        )
        handlers.append(fh)
    except OSError:  # 日志文件不可写时退化为仅控制台
        pass

    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


_setup_logging()

app = typer.Typer(
    name="tm1-suite",
    help="高性能 TM1 运维套件：Explorer / Audit / Graph 三视图统一元数据仓库",
    no_args_is_help=True,
)


@app.command()
def ingest(
    no_export: bool = typer.Option(False, "--no-export", help="跳过拉取，仅用已有 raw JSON 入库"),
    no_drop: bool = typer.Option(False, "--no-drop", help="不重建表（增量追加）"),
) -> None:
    """从 TM1 拉取元数据并写入 DuckDB + Parquet。"""
    settings = get_settings()

    if not no_export:
        from tm1_suite.ingest.exporter import Exporter

        try:
            Exporter(settings).export_all()
        except Exception as e:  # noqa: BLE001
            typer.echo(f"[错误] 拉取失败: {e}", err=True)
            raise typer.Exit(code=1)

    from tm1_suite.ingest.loader import Loader

    try:
        stats = Loader(settings).load(drop=not no_drop)
    except FileNotFoundError as e:
        typer.echo(f"[错误] {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo("入库统计:")
    for table, count in stats.items():
        typer.echo(f"  {table:32s}: {count}")


@app.command()
def status() -> None:
    """查看各表行数与库文件路径。"""
    settings = get_settings()
    store = Store(settings)

    typer.echo(f"数据库: {store.db_path}")
    for table, count in store.all_rows().items():
        typer.echo(f"  {table:32s}: {count}")


@app.command()
def check() -> None:
    """测试 TM1 连接并打印服务器信息。"""
    from tm1_suite.tm1.client import TM1Client

    settings = get_settings()
    typer.echo(f"连接 TM1: {settings.tm1_address}:{settings.tm1_port} ...")
    try:
        info = TM1Client(settings).check()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"[失败] 无法连接: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo("连接成功")
    typer.echo(f"  服务器: {info['server_name']}")
    typer.echo(f"  版本:   {info['product_version']}")
    typer.echo(
        f"  Cube={info['cubes']}, Process={info['processes']}, "
        f"Dimension={info['dimensions']}, Chore={info['chores']}"
    )


@app.command()
def query(cube: str = typer.Argument(..., help="Cube 名称")) -> None:
    """查询：谁写/读这个 Cube，以及它的维度。"""
    settings = get_settings()
    store = Store(settings)
    con = store.connect(read_only=True)
    try:
        summary = cube_summary(con, cube)
    finally:
        con.close()

    typer.echo(f"Cube: {cube}")
    typer.echo(f"  维度 ({len(summary['dimensions'])}): {', '.join(summary['dimensions']) or '-'}")
    typer.echo(f"  写入者 TI ({len(summary['writers'])}): {', '.join(summary['writers']) or '-'}")
    typer.echo(f"  读取者 TI ({len(summary['readers'])}): {', '.join(summary['readers']) or '-'}")
    typer.echo(
        f"  Rule 引用来源 Cube ({len(summary['rule_sources'])}): "
        f"{', '.join(summary['rule_sources']) or '-'}"
    )


@app.command()
def audit() -> None:
    """扫描前端 Excel 资产（applications/ + externals/），填充 Audit 视图。"""
    from tm1_suite.ingest.audit import load_audit

    settings = get_settings()
    try:
        stats = load_audit(settings)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"[错误] 审计扫描失败: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"前端资产: {stats['excel_assets']} 个")
    typer.echo(f"前端→后端映射: {stats['front_backend_mapping']} 个")


@app.command()
def web() -> None:
    """启动 Web UI（FastAPI）。"""
    import uvicorn

    settings = get_settings()
    typer.echo(f"启动 Web UI: http://{settings.web_host}:{settings.web_port}")
    uvicorn.run("tm1_suite.api.app:app", host=settings.web_host, port=settings.web_port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
