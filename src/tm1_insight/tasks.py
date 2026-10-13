"""Bounded local background jobs and rebuildable disk result cache (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class TaskBusy(Exception):
    pass


class TaskCancelled(Exception):
    pass


@dataclass
class ResultArtifact:
    path: Path
    index: Path
    owner: object

    def cleanup(self):self.owner.cleanup()


class TaskManager:
    def __init__(self, root: Path, *, max_workers: int = 1, max_records: int = 32,
                 max_cache_bytes: int = 256 * 1024 * 1024):
        self.root = Path(root)
        self.max_records = max_records
        self.max_cache_bytes = max_cache_bytes
        self._lock = threading.RLock()
        self._jobs = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tm1-analysis")
        self._slots = threading.BoundedSemaphore(max_workers + 1)

    def submit(self, key: str, worker, *, source: str) -> dict:
        digest = hashlib.sha256((source + "\0" + key).encode()).hexdigest()
        path = self.root / (digest + ".json")
        with self._lock:
            for job in self._jobs.values():
                if job["key"] == digest and job["status"] in {"queued", "running"}:
                    return self.state(job["task_id"])
            if not self._slots.acquire(blocking=False):
                raise TaskBusy("已有分析正在进行，请等待完成或取消当前任务。")
            terminal = [job for job in self._jobs.values() if job["status"] not in {"queued", "running"}]
            while len(self._jobs) >= self.max_records and terminal:
                old = terminal.pop(0)
                del self._jobs[old["task_id"]]
            if len(self._jobs) >= self.max_records:
                self._slots.release()
                raise TaskBusy("本地任务记录已满，请等待当前分析完成。")
            task_id = uuid.uuid4().hex
            job = {"task_id":task_id, "key":digest, "source":source, "path":path,
                   "status":"queued", "stage":"Queued", "stage_index":0, "stages_total":6,
                   "current":0, "total":None, "message":"等待本地分析", "created":time.monotonic(),
                   "cancel":threading.Event(), "cached":False, "error":None}
            self._jobs[task_id] = job
            self._pool.submit(self._run, job, worker)
            return self.state(task_id)

    def active(self, key: str, *, source: str) -> dict | None:
        """Find an in-flight job without touching an artifact being published."""
        digest = hashlib.sha256((source + "\0" + key).encode()).hexdigest()
        with self._lock:
            for job in self._jobs.values():
                if job["key"] == digest and job["status"] in {"queued", "running"}:
                    return self.state(job["task_id"])
        return None

    def _run(self, job, worker):
        result=None
        from tm1_insight.learning import pages
        def update(**fields):
            if job["cancel"].is_set():
                raise TaskCancelled()
            with self._lock:
                job.update(fields)
                job["message"] = fields.get("stage", job["stage"])

        try:
            update(status="running", stage="Checking local cache")
            path = job["path"]
            result=None
            if path.exists():
                try:
                    if pages.valid(path):os.utime(pages.index_path(path),None)
                    else:
                        with path.open(encoding="utf-8") as stream:result=json.load(stream)
                        os.utime(path, None)
                    update(cached=True)
                except (OSError, ValueError):
                    path.unlink(missing_ok=True)
            if not path.exists():
                result = worker(update)
                update(stage="Saving local result", stage_index=6)
                self.root.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix("." + job["task_id"] + ".tmp")
                try:
                    if isinstance(result,ResultArtifact):os.replace(result.path,temporary)
                    else:
                        with temporary.open("w", encoding="utf-8") as stream:json.dump(result, stream, ensure_ascii=False)
                    if temporary.stat().st_size > self.max_cache_bytes:
                        raise ValueError("Result exceeds local cache capacity")
                    os.replace(temporary, path)
                    if isinstance(result,ResultArtifact):os.replace(result.index,pages.index_path(path))
                finally:
                    temporary.unlink(missing_ok=True)
                    if isinstance(result,ResultArtifact):result.cleanup()
            if isinstance(result,dict) and str(result.get("version","")).startswith("study-") and not pages.valid(path):
                update(stage="建立分页检索索引",stage_index=6)
                pages.build(path,result)
            if pages.index_path(path).exists() and path.stat().st_size+pages.index_path(path).stat().st_size>self.max_cache_bytes:
                path.unlink(missing_ok=True);pages.index_path(path).unlink(missing_ok=True)
                raise ValueError("Result and index exceed local cache capacity")
            self._prune(path)
            update(status="completed", stage="Completed", stage_index=6, current=1, total=1)
        except TaskCancelled:
            with self._lock:
                job.update(status="cancelled", message="分析已取消")
        except Exception:
            # Do not put exception text (which can contain paths or credentials) in API responses.
            with self._lock:
                job.update(status="failed", error="本地分析失败；请检查数据格式或缩小范围后重试。", message="分析失败")
        finally:
            if isinstance(result,ResultArtifact):result.cleanup()
            with self._lock:
                job["finished"] = time.monotonic()
            self._slots.release()

    def _prune(self, protected: Path):
        from tm1_insight.learning.pages import index_path
        files = sorted(self.root.glob("*.json"), key=lambda p:max(p.stat().st_mtime_ns,index_path(p).stat().st_mtime_ns if index_path(p).exists() else 0))
        def size_of(path):return path.stat().st_size+(index_path(path).stat().st_size if index_path(path).exists() else 0)
        size = sum(size_of(p) for p in files)
        for path in files:
            if size <= self.max_cache_bytes:
                break
            if path != protected:
                size -= size_of(path)
                path.unlink(missing_ok=True)
                index_path(path).unlink(missing_ok=True)

    def state(self, task_id: str) -> dict:
        with self._lock:
            job = self._jobs[task_id]
            fields = ("task_id", "status", "stage", "stage_index", "stages_total", "current", "total",
                      "message", "cached", "error", "source")
            state = {key:job[key] for key in fields}
            elapsed = job.get("finished", time.monotonic()) - job["created"]
            state["elapsed_seconds"] = round(elapsed, 2)
            # Stage counts do not imply equal work. Only expose estimates based on a real object count.
            state["estimated_remaining_seconds"] = None
            return state

    def result(self, task_id: str, *, source: str) -> dict:
        with self._lock:
            job = self._jobs[task_id]
            if job["source"] != source:
                raise ValueError("数据源已切换；请在当前模型中重新分析。")
            if job["status"] != "completed":
                raise ValueError("分析尚未完成。")
            path = job["path"]
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)

    def cancel(self, task_id: str) -> dict:
        with self._lock:
            self._jobs[task_id]["cancel"].set()
            return self.state(task_id)

    def result_path(self, task_id: str, *, source: str) -> Path:
        with self._lock:
            job=self._jobs[task_id]
            if job["source"]!=source:raise ValueError("数据源已切换；请重新分析。")
            if job["status"]!="completed":raise ValueError("分析尚未完成。")
            if not job["path"].exists():raise FileNotFoundError("缓存已清理，请重新分析。")
            return job["path"]

    def close(self):
        self._pool.shutdown(wait=True)
