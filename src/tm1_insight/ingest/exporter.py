"""采集：并行拉取 TM1 对象并落盘为 JSON（raw 层，即「知识包」雏形）。

复用 tm1tree/main.py 的并行调度与断点续传逻辑，路径改为配置驱动。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from TM1py.Exceptions import TM1pyException

from tm1_insight.config import Settings
from tm1_insight.ingest.progress import Progress
from tm1_insight.tm1.client import TM1Client, safe_filename

logger = logging.getLogger(__name__)

_progress_lock = threading.Lock()


def save_json(data: Any, filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


class Exporter:
    def __init__(self, settings: Settings, progress: Progress | None = None, strict: bool = False):
        self.settings = settings
        self.client = TM1Client(settings)
        self.raw_dir = settings.raw_dir
        self.progress = progress
        self.strict = strict

    def _report(self, phase, done=None, total=None):
        if self.progress:
            self.progress(phase, done, total)

    # ---- 单对象：fetch + 落盘 ----
    def _export_one(self, tm1, obj_type: str, name: str, *args) -> tuple[str, bool, str | None]:
        filepath = self.raw_dir / obj_type / f"{safe_filename(name)}.json"
        if self.settings.tm1_skip_existing and filepath.exists():
            if obj_type!="cubes":return name, True, "skipped"
            try:
                existing=json.loads(filepath.read_text(encoding="utf-8"))
                if existing.get("rules_status")=="available":return name,True,"skipped"
            except (OSError,ValueError):pass
            # Legacy files without collection status cannot prove absent rules.
            # Re-fetch only when the user explicitly runs collection again.

        fetch: Callable = {
            "cubes": self.client.fetch_cube,
            "processes": self.client.fetch_process,
            "dimensions": self.client.fetch_dimension,
            "chores": self.client.fetch_chore,
        }[obj_type]

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                data = fetch(tm1, name, *args) if obj_type == "dimensions" else fetch(tm1, name)
                save_json(data, filepath)
                return name, True, None
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        logger.warning("%s 拉取失败: %s (%s)", obj_type, name, type(last_err).__name__)
        return name, False, type(last_err).__name__

    # ---- 并行调度 ----
    def _run_parallel(self, obj_type: str, names: list, extra_args: list | None = None,
                      phase: str | None = None) -> None:
        extra_args = extra_args or []
        total = len(names)
        phase = phase or obj_type
        self._report(phase, 0, total)
        if total == 0:
            logger.info("%s: 无对象", obj_type)
            return

        logger.info("开始导出 %s: %d 个", obj_type, total)
        start = datetime.now()
        counter = {"done": 0, "failed": 0}
        workers = self.settings.tm1_max_workers

        chunks: list[list] = [[] for _ in range(workers)]
        for i, name in enumerate(names):
            chunks[i % workers].append(name)

        def worker(chunk: list, worker_id: int) -> list:
            tm1 = self.client.connect()
            local_failed = []
            try:
                for item in chunk:
                    if isinstance(item, tuple):
                        result = self._export_one(tm1, obj_type, item[0], *item[1:])
                    else:
                        result = self._export_one(tm1, obj_type, item, *extra_args)
                    with _progress_lock:
                        counter["done"] += 1
                        if not result[1]:
                            counter["failed"] += 1
                            local_failed.append((result[0], result[2]))
                        self._report(phase, counter["done"], total)
                        if counter["done"] % 200 == 0 or counter["done"] == total:
                            logger.info(
                                "[%s] %d/%d (失败: %d)",
                                obj_type, counter["done"], total, counter["failed"],
                            )
            finally:
                try:
                    tm1.logout()
                except Exception:  # noqa: BLE001
                    pass
            return local_failed

        all_failed: list = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker, chunk, i) for i, chunk in enumerate(chunks)]
            for f in as_completed(futures):
                try:
                    all_failed.extend(f.result())
                except Exception as e:  # noqa: BLE001
                    logger.error("采集线程异常: %s", type(e).__name__)
                    if self.strict:
                        raise RuntimeError("Collection worker failed") from None

        elapsed = (datetime.now() - start).total_seconds()
        logger.info(
            "%s 完成: %d/%d, 失败 %d, 耗时 %.1fs",
            obj_type, counter["done"] - counter["failed"], total, counter["failed"], elapsed,
        )
        if all_failed:
            failed_path = self.raw_dir / f"failed_{obj_type}.txt"
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            with open(failed_path, "w", encoding="utf-8") as f:
                for name, err in all_failed:
                    f.write(f"{name}\t{err}\n")
        if self.strict and counter["failed"]:
            raise RuntimeError("Collection contains failed objects")

    # ---- 单维度增量补采 ----
    def recollect_dimension(self, name: str, *,
                            include_hierarchies: bool = True,
                            include_subset_definitions: bool = True,
                            attributes: list[str] | None = None,
                            elements_for_values: list[str] | None = None) -> dict:
        """对指定维度做增量补采：拉取完整层级/子集定义/所选属性值并落盘。

        只补采单个维度的 raw JSON（``raw_dir/dimensions/<name>.json``），
        不重采整个大型 TM1 模型。返回补采结果摘要。
        """
        self.settings.ensure_dirs()
        (self.raw_dir / "dimensions").mkdir(parents=True, exist_ok=True)
        is_system = name.startswith("}")
        with self.client.connect() as tm1:
            try:
                data = self.client.fetch_dimension_incremental(
                    tm1, name,
                    include_hierarchies=include_hierarchies,
                    include_subset_definitions=include_subset_definitions,
                    attributes=attributes,
                    elements_for_values=elements_for_values,
                )
            finally:
                try:
                    tm1.logout()
                except Exception:  # noqa: BLE001
                    pass
        filepath = self.raw_dir / "dimensions" / f"{safe_filename(name)}.json"
        save_json(data, filepath)
        summary = {
            "name": name,
            "is_system": is_system,
            "filepath": str(filepath),
            "hierarchy_names": data.get("hierarchy_names", []),
            "hierarchy_count": len(data.get("hierarchies", [])),
            "subset_definition_count": len(data.get("subset_definitions", [])),
            "attribute_values": list((data.get("attribute_values") or {}).get("attributes", {}).keys()),
        }
        logger.info("增量补采完成: %s → %s", name, filepath)
        return summary

    # ---- 主流程 ----
    def export_all(self) -> dict:
        self.settings.ensure_dirs()
        for sub in ("cubes", "processes", "dimensions", "chores", "security"):
            (self.raw_dir / sub).mkdir(parents=True, exist_ok=True)

        # 1. 对象名 + 安全信息
        self._report("enumerate")
        logger.info("连接 TM1: %s:%s", self.settings.tm1_address, self.settings.tm1_port)
        names = self.client.list_all_names()
        logger.info(
            "连接成功: Cube=%d, Process=%d, Dimension=%d, Chore=%d",
            len(names["cubes"]), len(names["processes"]),
            len(names["dimensions"]), len(names["chores"]),
        )
        self._report("security")
        groups, clients = self.client.fetch_security()

        # 2. 分类型并行导出（各阶段互不阻断，失败只记日志，保证 loader 一定执行）
        for phase, args in (
            ("cubes", (names["cubes"],)),
            ("processes", (names["processes"],)),
        ):
            try:
                self._run_parallel(phase, *args)
            except Exception as e:  # noqa: BLE001
                logger.error("导出 %s 异常: %s", phase, type(e).__name__)
                if self.strict:
                    raise

        system_dims = [(n, True) for n in names["dimensions"] if n.startswith("}")]
        business_dims = [(n, False) for n in names["dimensions"] if not n.startswith("}")]
        logger.info("业务维度: %d, 系统维度: %d", len(business_dims), len(system_dims))
        for phase, kind, args in (
            ("dimensions_business", "dimensions", (business_dims,)),
            ("dimensions_system", "dimensions", (system_dims,)),
            ("chores", "chores", (names["chores"],)),
        ):
            try:
                self._run_parallel(kind, *args, phase=phase)
            except Exception as e:  # noqa: BLE001
                logger.error("导出 %s 异常: %s", phase, type(e).__name__)
                if self.strict:
                    raise

        # 3. 安全信息 + 总索引
        self._report("raw_index")
        save_json(groups, self.raw_dir / "security" / "groups.json")
        save_json(clients, self.raw_dir / "security" / "clients.json")
        index = {
            "cubes": names["cubes"],
            "processes": names["processes"],
            "dimensions_business": [n for n, _ in business_dims],
            "dimensions_system": [n for n, _ in system_dims],
            "chores": names["chores"],
        }
        save_json(index, self.raw_dir / "_index.json")

        logger.info("全部导出完成 → %s", self.raw_dir)
        return {
            "cubes": len(names["cubes"]),
            "processes": len(names["processes"]),
            "dimensions": len(names["dimensions"]),
            "chores": len(names["chores"]),
            "raw_dir": str(self.raw_dir),
        }
