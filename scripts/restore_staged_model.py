"""离线恢复暂存模型：只重跑 Loader + 血缘 + Parquet + 校验，不连 TM1 Server。

用法（在拥有临时目录的机器上执行）：

    python scripts/restore_staged_model.py D:/3.PA_Software/2.tools/.../collections/model-m4j1_j1w

它会：
1. 复用临时目录里已有的 raw/*.json 原始文件（不重新采集）。
2. 在临时目录内新建独立子目录 <model>/staged_rebuild/ 作为独立 data_dir，
   重建 DuckDB + Parquet，绝不触碰正式 DuckDB 或 WAL。
3. 跑完整 Loader（含血缘解析、Parquet 导出），输出 processes / ti_summary 计数。
4. 跑名称级对账，输出缺失/重复对象名（若仍有缺失会非零退出）。
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    model_dir = Path(sys.argv[1]).resolve()
    raw = model_dir / "raw"
    if not raw.is_dir():
        print(f"[FATAL] raw 目录不存在: {raw}")
        print("原始 JSON 不完整，停止恢复，不伪造对象。")
        return 1

    # 独立暂存 data_dir，不碰正式库。
    staged_data = model_dir / "staged_rebuild"
    staged_data.mkdir(parents=True, exist_ok=True)

    # 注入 src，构造 settings。
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))

    from tm1_insight.config import Settings
    from tm1_insight.ingest.loader import Loader, _reconcile_names, _index_names
    from tm1_insight.ingest.loader import _load_json_dir

    settings = Settings(data_dir=str(staged_data), database_file=None)

    # 直接把临时目录的 raw 作为输入（复用原始 JSON，不重采）。
    # Loader 通过 settings.raw_dir 读数据，这里把 raw 拷/链到 staged_data/raw。
    import shutil
    staged_raw = staged_data / "raw"
    if not staged_raw.exists():
        # 软链/复制 raw 到独立目录；优先复制以隔离（raw 可能很大，用 dirs_exist_ok）。
        shutil.copytree(raw, staged_raw)

    # 先做名称级对账（只读 raw），确认没有下划线 Process 被丢。
    rows, failures = _load_json_dir(staged_raw, "processes")
    rec = _reconcile_names(staged_raw, "processes", rows, failures)
    print("=== 名称级对账（修复后）===")
    print(f"  枚举 processes: {rec['expected_count']}")
    print(f"  实际读入行数: {rec['actual_rows']}")
    print(f"  唯一名称: {rec['actual_unique']}")
    print(f"  缺失: {rec['missing']}")
    print(f"  重复: {rec['duplicates']}")
    print(f"  读取失败: {rec['read_failures']}")

    if rec["missing"]:
        print("[FAIL] 仍有缺失对象，不继续入库。请检查以上缺失名单。")
        return 1

    # 完整 Loader（对象入库 + 关系 + 血缘 + Parquet）。
    loader = Loader(settings, strict=True)
    stats = loader.load(drop=True)

    print("=== 完整入库统计 ===")
    for k in ("processes", "ti_summary", "cubes", "dimensions", "chores"):
        print(f"  {k}: {stats.get(k)}")

    # 校验：processes 与 ti_summary 应一致，且等于枚举数。
    ok = stats.get("processes") == rec["expected_count"]
    ok = ok and stats.get("ti_summary") == stats.get("processes")
    print("=== 结果 ===")
    print(f"  processes == ti_summary == 枚举数: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
