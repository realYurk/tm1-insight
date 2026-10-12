"""Synthetic local jobs: cancellation, cache bounds and customer isolation."""
import threading
import time

import pytest

from tm1_insight.tasks import TaskBusy, TaskManager


def finished(manager, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = manager.state(task_id)
        if state["status"] not in {"queued", "running"}:
            return state
        time.sleep(.005)
    pytest.fail("Local test job did not finish")


def test_task_progress_cache_survives_restart_and_is_bound_to_source(tmp_path):
    manager = TaskManager(tmp_path)
    started, release = threading.Event(), threading.Event()

    def work(update):
        update(stage="Process Behavior Analysis", stage_index=3, current=1, total=2)
        started.set()
        assert release.wait(5)
        return {"observed":"synthetic"}

    try:
        task = manager.submit("scope", work, source="A")
        assert started.wait(5)
        assert manager.state(task["task_id"])["current"] == 1
        assert manager.submit("scope", work, source="A")["task_id"] == task["task_id"]
        release.set()
        assert finished(manager, task["task_id"])["status"] == "completed"
        assert manager.result(task["task_id"], source="A") == {"observed":"synthetic"}
        with pytest.raises(ValueError):
            manager.result(task["task_id"], source="B")
    finally:
        release.set(); manager.close()
    manager = TaskManager(tmp_path)
    try:
        def should_not_run(update):
            pytest.fail("Completed disk result was not reused")
        cached = manager.submit("scope", should_not_run, source="A")
        assert finished(manager, cached["task_id"])["cached"]
        different = manager.submit("scope", lambda update:{"observed":"other customer"}, source="B")
        assert not finished(manager, different["task_id"])["cached"]
    finally:
        manager.close()


def test_failed_task_does_not_expose_exception_contents(tmp_path):
    manager = TaskManager(tmp_path)
    def fail(update):
        raise RuntimeError("synthetic-private-credential")
    try:
        task = manager.submit("failure", fail, source="A")
        state = finished(manager, task["task_id"])
        assert state["status"] == "failed"
        assert "synthetic-private-credential" not in str(state)
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        manager.close()


def test_cancel_and_bounded_queue(tmp_path):
    manager = TaskManager(tmp_path)
    started, release = threading.Event(), threading.Event()
    def work(update):
        started.set()
        assert release.wait(5)
        update(stage="Still working")
        return {}
    try:
        first = manager.submit("one", work, source="A")
        assert started.wait(5)
        second = manager.submit("two", work, source="A")
        with pytest.raises(TaskBusy):
            manager.submit("three", work, source="A")
        manager.cancel(first["task_id"])
        release.set()
        assert finished(manager, first["task_id"])["status"] == "cancelled"
        assert finished(manager, second["task_id"])["status"] == "completed"
    finally:
        release.set(); manager.close()


def test_disk_cache_and_in_memory_records_are_bounded(tmp_path):
    manager = TaskManager(tmp_path, max_cache_bytes=1000, max_records=2)
    try:
        tasks = []
        for index in range(4):
            task = manager.submit(str(index), lambda update:{"payload":"x" * 700}, source="A")
            assert finished(manager, task["task_id"])["status"] == "completed"
            tasks.append(task)
        assert sum(path.stat().st_size for path in tmp_path.glob("*.json")) <= 1000
        with pytest.raises(KeyError):
            manager.state(tasks[0]["task_id"])
        assert manager.result(tasks[-1]["task_id"], source="A")["payload"] == "x" * 700
    finally:
        manager.close()
