"""Real Exporter/Loader against a synthetic TM1 transport; never connect to a server."""
import hashlib
import importlib
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import tm1_insight.config as config
import tm1_insight.datasource as ds
from tm1_insight.ingest.progress import INGEST_STAGES, AUDIT_STAGES, stage_progress
from test_datasource import _make_real_db


class SyntheticTM1:
    gate = None
    failure = None

    def __init__(self, settings):
        pass

    def connect(self):
        return SimpleNamespace(logout=lambda: None)

    def list_all_names(self):
        if self.gate:
            assert self.gate.wait(10)
        if self.failure == "connect":
            raise RuntimeError("synthetic-private-value-must-not-appear")
        return {"cubes": ["ExampleSource", "ExampleResult"], "processes": ["CopyExample"],
                "dimensions": ["Version"], "chores": ["ExampleSchedule"]}

    def fetch_security(self):
        return [], []

    def fetch_cube(self, tm1, name):
        if self.failure == "cube":
            raise RuntimeError("synthetic-private-value-must-not-appear")
        return {"name": name, "dimensions": ["Version"], "rules": "", "has_rules": False,
                "rules_status": "available"}

    def fetch_process(self, tm1, name):
        return {"name": name, "prolog": "ExecuteProcess(pDynamicChild);",
                "data": "vValue = CellGetN('ExampleSource', 'Actual');\nCellPutN(vValue, 'ExampleResult', 'Actual');"}

    def fetch_dimension(self, tm1, name, light):
        return {"name": name, "elements": ["Actual"], "element_count": 1,
                "attributes": {}, "edges": [], "subsets": []}

    def fetch_chore(self, tm1, name):
        return {"name": name, "processes": [{"name": "CopyExample", "step_order": 1}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    api = importlib.import_module("tm1_insight.api.app")
    exporter = importlib.import_module("tm1_insight.ingest.exporter")
    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "_DATA_DIR_OVERRIDE", None)
    monkeypatch.setattr(ds, "_source_cache", None)
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    config.get_settings.cache_clear()
    source = _make_real_db(tmp_path / "local")
    config.set_data_dir(source)
    config.get_settings().tm1_max_workers = 1
    monkeypatch.setattr(SyntheticTM1, "gate", None)
    monkeypatch.setattr(SyntheticTM1, "failure", None)
    monkeypatch.setattr(exporter, "TM1Client", SyntheticTM1)
    monkeypatch.setattr(api, "_ingest_state", {"running": False, "done": False, "error": None, "stats": None, "progress": None})
    monkeypatch.setattr(api, "_audit_state", {"running": False, "done": False, "error": None, "stats": None, "progress": None})
    monkeypatch.setattr(api, "_ingest_cancel", threading.Event())
    monkeypatch.setattr(api, "_audit_cancel", threading.Event())
    events = []

    def record(stages, phase, done=None, total=None):
        result = stage_progress(stages, phase, done, total)
        events.append((len(stages), phase, result))
        return result

    monkeypatch.setattr(api, "stage_progress", record)
    with TestClient(api.app) as client:
        yield SimpleNamespace(client=client, api=api, source=source, root=tmp_path, events=events)
        if SyntheticTM1.gate:
            SyntheticTM1.gate.set()
        wait_done(client, "ingest")
        wait_done(client, "audit")
    config.get_settings.cache_clear()


def wait_done(client, kind):
    deadline = time.monotonic() + 15
    while True:
        response = client.get(f"/api/{kind}/status")
        state = response.json()
        if not state.get("running"):
            return state
        assert time.monotonic() < deadline, state
        time.sleep(.02)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_success_builds_new_model_and_reports_real_stages_without_touching_source(env):
    before = sha(env.source)
    assert env.client.post("/api/ingest", json={}).status_code == 200
    result = wait_done(env.client, "ingest")
    assert not result["error"] and result["stats"]["cubes"] == 2
    current = config.get_settings().db_path
    assert current.is_relative_to(env.root / "collections") and current != env.source
    assert sha(env.source) == before
    phases = {phase for size, phase, _ in env.events if size == len(INGEST_STAGES)}
    assert phases == {phase for phase, _ in INGEST_STAGES}
    counters = [item for _, phase, item in env.events if phase == "cubes"]
    assert [item["done"] for item in counters] == [0, 1, 2]
    assert [item["percent"] for item in counters] == [0, 50, 100]
    assert counters[-1]["stage"] == 3 and counters[-1]["stages"] == 16
    assert "CopyExample" in env.client.get("/chores").text
    assert env.client.get("/api/ingest/status").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure", ["connect", "cube", "parser"])
def test_failure_never_switches_or_rebuilds_original_and_does_not_expose_error(env, monkeypatch, failure):
    before = sha(env.source)
    if failure == "parser":
        from tm1_insight.ingest.loader import Loader
        def fail(*args):
            raise RuntimeError("synthetic-private-value-must-not-appear")
        monkeypatch.setattr(Loader, "_insert_lineage", fail)
    else:
        monkeypatch.setattr(SyntheticTM1, "failure", failure)
    assert env.client.post("/api/ingest", json={}).status_code == 200
    result = wait_done(env.client, "ingest")
    assert result["error"] and "synthetic-private-value" not in str(result)
    assert config.get_settings().db_path == env.source and sha(env.source) == before


def test_collecting_source_cannot_override_a_new_user_selection(env, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(SyntheticTM1, "gate", gate)
    before = sha(env.source)
    assert env.client.post("/api/ingest", json={}).status_code == 200
    other = _make_real_db(env.root / "other")
    assert env.client.post("/api/datasource/use", json={"source": "local", "path": str(other)}).status_code == 200
    gate.set()
    result = wait_done(env.client, "ingest")
    assert result["error"] and config.get_settings().db_path == other
    assert sha(env.source) == before


def test_start_reservation_and_checkpoint_cancel_preserve_original(env, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(SyntheticTM1, "gate", gate)
    before = sha(env.source)
    assert env.client.post("/api/ingest", json={}).status_code == 200
    assert env.client.post("/api/ingest", json={}).status_code == 409
    assert env.client.get("/api/ingest/status").json()["running"]
    assert env.client.post("/api/ingest/cancel").json()["cancel_requested"]
    gate.set()
    result = wait_done(env.client, "ingest")
    assert result["cancelled"] and "已取消" in result["error"]
    assert config.get_settings().db_path == env.source and sha(env.source) == before


def test_corrupt_or_incomplete_new_database_is_not_activated(env, monkeypatch):
    from tm1_insight.ingest.loader import Loader
    original = Loader.load
    def incomplete(self, drop=True):
        result = original(self, drop)
        with self.store.connect() as con:
            con.execute("DELETE FROM processes")
        return result
    monkeypatch.setattr(Loader, "load", incomplete)
    assert env.client.post("/api/ingest", json={}).status_code == 200
    assert wait_done(env.client, "ingest")["error"]
    assert config.get_settings().db_path == env.source


def test_scan_stages_and_cancellation_keep_last_complete_sidecar(env, monkeypatch):
    from openpyxl import Workbook
    from tm1_insight.audit_workspace import workspace
    import tm1_insight.ingest.audit as audit
    apps = env.root / "frontend"
    apps.mkdir()
    book = Workbook()
    book.active["A1"] = '=DBRW("TestCube","Actual")'
    book.save(apps / "Example.xlsx")
    paths = {"applications": str(apps), "externals": "", "work_dir": str(env.root / "scan-cache")}
    before = sha(env.source)
    assert env.client.post("/api/audit", json=paths).status_code == 200
    result = wait_done(env.client, "audit")
    assert not result["error"] and result["stats"]["excel_assets"] == 1
    phases = {phase for size, phase, _ in env.events if size == len(AUDIT_STAGES)}
    assert phases == {phase for phase, _ in AUDIT_STAGES}
    assert any(item["stage"] == 3 and item["done"] == item["total"] == 1 for _, _, item in env.events)
    sidecar = workspace(config.get_settings()).db_path
    previous_scan = sha(sidecar)
    entered, release = threading.Event(), threading.Event()
    original = audit._scan_excel_cached
    def blocked(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result
    monkeypatch.setattr(audit, "_scan_excel_cached", blocked)
    assert env.client.post("/api/audit", json=paths).status_code == 200
    assert entered.wait(5)
    try:
        assert env.client.post("/api/audit/cancel").json()["cancel_requested"]
    finally:
        release.set()
    assert wait_done(env.client, "audit")["cancelled"]
    assert sha(sidecar) == previous_scan and sha(env.source) == before


def test_settings_and_audit_share_visible_real_progress_contract(env):
    settings = env.client.get("/settings").text
    audit = env.client.get("/audit").text
    assert 'id="ingest-progress"' in settings and 'id="audit-progress"' in settings
    assert "job-progress.js" in settings and "job-progress.js" in audit
    assert "不代表总耗时进度" in settings and "取消任务" in audit
    assert "校验成功后切换，原模型保留" in settings


def test_lineage_cancellation_does_not_queue_entire_model(env, monkeypatch):
    import concurrent.futures
    from tm1_insight.ingest.loader import Loader
    from tm1_insight.store.db import Store
    from tm1_insight.tasks import TaskCancelled
    submitted = []

    class RecordingPool:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def map(self, function, items, **kwargs):
            submitted.append(len(items))
            return map(function, items)

    def cancel_after_one(phase, done, total):
        if done == 1:
            raise TaskCancelled()

    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", RecordingPool)
    model = config.get_settings()
    processes = [{"name": f"Synthetic.{i}", "prolog": "", "data": "", "parameters": []} for i in range(1128)]
    with Store(model).connect(read_only=True) as con:
        with pytest.raises(TaskCancelled):
            Loader(model, progress=cancel_after_one)._insert_lineage(con, processes)
    assert submitted == [16]  # One worker: only the first bounded batch was submitted.


@pytest.mark.parametrize("kind", ["ingest", "audit"])
@pytest.mark.parametrize("failure_point", ["construct", "start"])
def test_worker_start_failure_releases_reservation(env, monkeypatch, kind, failure_point):
    class FailedThread:
        def __init__(self, *args, **kwargs):
            if failure_point == "construct":
                raise RuntimeError("synthetic worker cannot be constructed")
        def start(self):
            raise RuntimeError("synthetic worker cannot start")
    monkeypatch.setattr(env.api, "threading", SimpleNamespace(Thread=FailedThread))
    apps = env.root / "frontend"
    apps.mkdir()
    paths = {"applications": str(apps), "externals": "", "work_dir": str(env.root / "scan-cache")}
    response = env.client.post(f"/api/{kind}", json=paths if kind == "audit" else {})
    assert response.status_code == 503
    state = env.client.get(f"/api/{kind}/status").json()
    assert not state["running"] and state["done"] and state["error"]
