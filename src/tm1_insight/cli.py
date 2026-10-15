"""CLI 入口（typer）。

命令：
    tm1-insight ingest [--no-export] [--no-drop]   拉取 + 入库
    tm1-insight status                               各表行数
    tm1-insight query <cube>                         查询 Cube 的读写者与维度
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import typer

from tm1_insight.config import get_settings
from tm1_insight.store.db import Store
from tm1_insight.store.queries import cube_summary


def _setup_logging() -> None:
    """配置日志：控制台 + 滚动文件（用户数据目录 logs/tm1-insight.log）。

    日志写到用户数据目录（Portable 为 %LOCALAPPDATA%\\TM1 Insight\\logs），
    而非程序目录，保证程序放在只读位置也能记录日志。
    """
    from tm1_insight.config import get_settings

    try:
        log_dir = get_settings().logs_dir
    except Exception:  # noqa: BLE001  # 配置加载失败时退化为程序目录
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    try:
        fh = RotatingFileHandler(
            log_dir / "tm1-insight.log",
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
    name="tm1-insight",
    help="TM1 Insight：高性能 TM1 运维套件（Explorer / Audit / Graph 三视图统一元数据仓库）",
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
        from tm1_insight.ingest.exporter import Exporter

        try:
            Exporter(settings).export_all()
        except Exception as e:  # noqa: BLE001
            typer.echo(f"[错误] 拉取失败: {e}", err=True)
            raise typer.Exit(code=1)

    from tm1_insight.ingest.loader import Loader

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


@app.command("recollect-dimension")
def recollect_dimension(
    name: str = typer.Argument(..., help="要补采的维度名称（如 'Car Model'）"),
    attributes: str = typer.Option("", "--attributes", help="逗号分隔的属性名，如 'Power,Brand'；留空则只补采层级与子集定义"),
    elements: str = typer.Option("", "--elements", help="逗号分隔的元素名（采集属性值范围）；留空则不采集属性值"),
    no_hierarchies: bool = typer.Option(False, "--no-hierarchies", help="跳过层级元数据补采"),
    no_subsets: bool = typer.Option(False, "--no-subsets", help="跳过子集定义补采"),
    reload: bool = typer.Option(False, "--reload", help="补采后重新入库（重建 DuckDB）"),
) -> None:
    """对指定维度做增量补采（层级/公共子集/所选属性值），不重采整个模型。"""
    settings = get_settings()
    from tm1_insight.ingest.exporter import Exporter

    attr_list = [a.strip() for a in attributes.split(",") if a.strip()] if attributes else None
    elem_list = [e.strip() for e in elements.split(",") if e.strip()] if elements else None
    if attr_list and not elem_list:
        typer.echo("[提示] 指定了属性但未指定元素范围，将不采集任何属性值（避免全量拉取）。", err=True)

    try:
        summary = Exporter(settings).recollect_dimension(
            name,
            include_hierarchies=not no_hierarchies,
            include_subset_definitions=not no_subsets,
            attributes=attr_list,
            elements_for_values=elem_list,
        )
    except Exception as e:  # noqa: BLE001
        typer.echo(f"[错误] 增量补采失败: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo("增量补采完成：")
    typer.echo(f"  维度:        {summary['name']}")
    typer.echo(f"  层级:        {summary['hierarchy_count']} 个 {summary['hierarchy_names']}")
    typer.echo(f"  子集定义:    {summary['subset_definition_count']} 个")
    typer.echo(f"  属性值:      {summary['attribute_values'] or '-'}")
    typer.echo(f"  落盘:        {summary['filepath']}")

    if reload:
        from tm1_insight.ingest.loader import Loader
        try:
            stats = Loader(settings).load(drop=True)
        except FileNotFoundError as e:
            typer.echo(f"[错误] {e}", err=True)
            raise typer.Exit(code=1)
        typer.echo("已重新入库（dimension_metadata 同步更新）。")


@app.command()
def check() -> None:
    """测试 TM1 连接并打印服务器信息。"""
    from tm1_insight.tm1.client import TM1Client

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
    from tm1_insight.ingest.audit import load_audit

    settings = get_settings()
    try:
        stats = load_audit(settings)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"[错误] 审计扫描失败: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"前端资产: {stats['excel_assets']} 个")
    typer.echo(f"前端→后端映射: {stats['front_backend_mapping']} 个")


@app.command()
def web(
    no_browser: bool = typer.Option(False, "--no-browser", help="不自动打开浏览器"),
) -> None:
    """启动 Web UI（FastAPI），端口被占用时自动递增，自动打开浏览器。"""
    import uvicorn

    from tm1_insight.portable import pick_port, start_browser_thread

    settings = get_settings()
    settings.ensure_dirs()

    port = pick_port(settings.web_host, settings.web_port)
    if port != settings.web_port:
        typer.echo(f"端口 {settings.web_port} 被占用，改用 {port}")

    typer.echo(f"启动 Web UI: http://127.0.0.1:{port}")
    if not no_browser:
        start_browser_thread(port)

    uvicorn.run("tm1_insight.api.app:app", host=settings.web_host, port=port)


@app.command()
def study(query: str = typer.Option("*", "--query", help="功能关键词；* 为整模型"),
          output: Path = typer.Option(None, "--output", help="本地私有教材输出目录")) -> None:
    """只读分析当前本地模型，生成无需 AI 的学习手册和业务地图。"""
    import json
    from tm1_insight.learning.engine import build_report, markdown
    settings = get_settings()
    if not settings.db_path.exists():
        raise typer.BadParameter("未找到当前本地模型，请先在设置中选择数据库。")
    destination = output or settings.user_data_root / "cache" / "learning"
    destination.mkdir(parents=True, exist_ok=True)
    con = Store(settings).connect(read_only=True)
    try: report = build_report(con, query)
    finally: con.close()
    (destination / "study.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path = destination / "READ_ME_FIRST.md"
    path.write_text(markdown(report), encoding="utf-8")
    typer.echo(f"私有学习手册已保存：{path}")
    typer.echo("结果含模型知识，仅供本地使用，禁止发布到公共空间。")


@app.command("study-all")
def study_all(root:Path=typer.Option(...,"--root",help="只读扫描的本地数据目录"),
              output:Path=typer.Option(None,"--output",help="位于原始数据目录之外的私有报告目录")):
    """盘点整个目录，为每份模型分别生成教材，不合并不同快照。"""
    from tm1_insight.learning.inventory import study_directory
    settings=get_settings()
    destination=output or settings.user_data_root/"cache"/"learning-all"
    result=study_directory(settings,root,destination,lambda n,total:typer.echo(f"分析本地仓库 {n}/{total}"))
    typer.echo(f"已盘点 {result['files']} 个文件，分析 {len(result['models'])} 份独立模型。")
    typer.echo(f"私有报告：{destination / '从这里开始.md'}；禁止上传。")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
