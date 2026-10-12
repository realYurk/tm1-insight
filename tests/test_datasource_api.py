"""Task 19 数据源 API 与页面测试。

验证：
- 各主要页面在「无数据 / Demo」下不返回 500（Loading/Empty 兜底）
- 数据源 API（status / detect / use）行为正确
- Demo 模式下 Dashboard/Cubes/Processes/Dimensions 有数据

铁律：绝不触碰真实 data/。用 TM1_INSIGHT_HOME 指向临时目录隔离。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tm1_insight.config as config  # noqa: E402
import tm1_insight.datasource as ds  # noqa: E402
from tm1_insight.config import set_data_dir, get_settings  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """构造一个隔离环境的 FastAPI TestClient（Demo 兜底）。"""
    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "app")
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    set_data_dir(None)
    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    from tm1_insight.api.app import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# 页面不 500（无数据 / Demo 兜底）
# ---------------------------------------------------------------------------

def test_all_pages_no_500_in_demo(client):
    """Demo 兜底后，所有主要页面都应返回 200。"""
    for path in ["/", "/cubes", "/processes", "/dimensions", "/graph",
                 "/impact", "/compare", "/audit", "/codegen", "/settings", "/learn", "/experience"]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_learning_job_results_and_templates(client):
    import io,time,zipfile
    response=client.post('/api/learning/tasks',json={'query':'Load'})
    assert response.status_code==202
    task=response.json()['task_id']
    deadline=time.monotonic()+5
    while True:
        status=client.get('/api/learning/tasks/'+task).json()
        if status['status'] not in {'queued','running'}:break
        assert time.monotonic()<deadline
        time.sleep(.01)
    assert status['status']=='completed'
    result=client.get(f'/api/learning/tasks/{task}/result?section=processes&limit=1').json()
    assert len(result['items'])==1
    assert result['items'][0]['process']=='Load_Sales'
    exported=client.post(f'/api/learning/tasks/{task}/export')
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert 'READ_ME_FIRST.md' in archive.namelist()
        assert not json.loads(archive.read('study.json'))['privacy']['contains_source']
    assert len(client.get('/api/learning/templates').json())>=10
    assert 'nEnableExample = 0' in client.get('/api/learning/templates/proportion').json()['prolog']
    assert client.get('/api/learning/templates/unknown').status_code==404
    cached=client.post('/api/learning/tasks',json={'query':'Load'}).json()['task_id']
    deadline=time.monotonic()+5
    while client.get('/api/learning/tasks/'+cached).json()['status'] in {'queued','running'}:
        assert time.monotonic()<deadline
        time.sleep(.01)
    assert client.get('/api/learning/tasks/'+cached).json()['cached']
    from test_datasource import _make_real_db
    other=_make_real_db(get_settings().user_data_root/'different-model')
    assert client.post('/api/datasource/use',json={'source':'local','path':str(other)}).status_code==200
    assert client.get(f'/api/learning/tasks/{task}/result').status_code==409


def test_learning_worker_cancellation_cleans_temporary_output(client):
    from tm1_insight.learning.worker import isolated_report
    from tm1_insight.tasks import TaskCancelled
    client.get('/')
    settings=get_settings()
    def cancel(**event):raise TaskCancelled()
    with pytest.raises(TaskCancelled):isolated_report(settings,'*',cancel)
    assert not list((settings.user_data_root/'cache'/'learning-workers').iterdir())


def test_audit_paths_and_sidecar_preserve_source(client,tmp_path):
    import hashlib,time
    from openpyxl import Workbook
    client.get('/')
    source=Path(client.get('/api/datasource/status').json()['db_path'])
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    apps=tmp_path/'separate-drive-apps';apps.mkdir()
    work=tmp_path/'separate-drive-cache'
    book=Workbook();book.active['A1']='=DBRW("Sales","Actual","2026")';book.save(apps/'small.xlsx')
    paths={'applications':str(apps),'externals':'','work_dir':str(work)}
    assert client.post('/api/audit/config',json=paths).status_code==200
    assert client.get('/api/audit/config').json()==paths
    response=client.post('/api/audit',json=paths)
    assert response.status_code==200
    deadline=time.monotonic()+5
    while True:
        state=client.get('/api/audit/status').json()
        if not state['running']:break
        assert time.monotonic()<deadline
        time.sleep(.01)
    assert not state['error']
    assert state['stats']['excel_assets']==1
    assert list(work.rglob('audit.duckdb'))
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    assert 'small.xlsx' in client.get('/audit').text
    assert '/explorer/cube/Sales' in client.get('/audit').text
    invalid={**paths,'applications':str(tmp_path/'missing')}
    assert client.post('/api/audit/config',json=invalid).status_code==400
    assert client.get('/api/audit/config').json()==paths


def test_audit_initialization_failure_leaves_no_partial_database(client,tmp_path,monkeypatch):
    import tm1_insight.audit_workspace as audit
    client.get('/')
    settings=get_settings()
    expected=audit.workspace(settings).db_path
    original=audit.ALL_TABLES
    monkeypatch.setattr(audit,'ALL_TABLES',{'invalid':'THIS IS NOT SQL'})
    with pytest.raises(Exception):
        audit.workspace(settings,initialize=True)
    assert not expected.exists()
    assert not list(expected.parent.glob('audit-init-*'))
    monkeypatch.setattr(audit,'ALL_TABLES',original)
    assert audit.workspace(settings,initialize=True).db_path.exists()


def test_study_cli_writes_private_report_without_changing_source(client,tmp_path):
    import hashlib
    from typer.testing import CliRunner
    from tm1_insight.cli import app
    client.get('/')
    source=get_settings().db_path
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    destination=tmp_path/'private-study'
    result=CliRunner().invoke(app,['study','--query','*','--output',str(destination)])
    assert result.exit_code==0,result.output
    assert (destination/'READ_ME_FIRST.md').exists()
    assert json.loads((destination/'study.json').read_text(encoding='utf-8'))['summary']['processes']==3
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before


def test_web_opens_selected_port_once_and_supports_no_browser(client,monkeypatch):
    from typer.testing import CliRunner
    from tm1_insight.cli import app
    import tm1_insight.portable as portable
    import uvicorn
    opened=[]
    started=[]
    monkeypatch.setattr(portable,'pick_port',lambda *args:8769)
    monkeypatch.setattr(portable,'start_browser_thread',lambda port:opened.append(port))
    monkeypatch.setattr(uvicorn,'run',lambda *args,**kwargs:started.append(kwargs['port']))
    result=CliRunner().invoke(app,['web'])
    assert result.exit_code==0,result.output
    assert opened==[8769] and started==[8769]
    opened.clear()
    assert CliRunner().invoke(app,['web','--no-browser']).exit_code==0
    assert not opened


def test_comparison_has_fast_shell_and_honest_sample_count(client):
    shell = client.get("/compare")
    assert "comparison-state" in shell.text
    assert "render=true" in shell.text
    result = client.get("/compare?render=true")
    assert result.status_code == 200
    assert "已采样 3 个" in result.text
    assert "完整历史比较尚未实现" in result.text


def test_impact_distinguishes_dependents_from_dependencies(client):
    response = client.get("/impact", params={"source":"Sales"})
    assert response.status_code == 200
    assert "Load_Sales" in response.text
    assert "结构依赖方" in response.text
    assert "不能直接证明" in response.text


def test_dashboard_has_data_in_demo(client):
    """Demo 模式下 Dashboard 显示数据规模（不再是空白）。"""
    r = client.get("/")
    assert r.status_code == 200
    # Demo 有 3 个 cube，首页应显示数据规模而非「欢迎使用」
    assert "Demo Mode" in r.text or "数据规模" in r.text


def test_cubes_page_has_data_in_demo(client):
    """Demo 模式下 Cubes 页有数据。"""
    r = client.get("/cubes")
    assert r.status_code == 200
    assert "Sales" in r.text


# ---------------------------------------------------------------------------
# 数据源 API
# ---------------------------------------------------------------------------

def test_datasource_status(client):
    """/api/datasource/status 返回结构化的数据源状态。"""
    r = client.get("/api/datasource/status")
    assert r.status_code == 200
    j = r.json()
    assert "type" in j
    assert "counts" in j
    # 首次访问自动 Demo 兜底（通过 / 触发），但 status 本身只读检测
    # 这里 status 可能在 empty 或 demo，都应是合法值
    assert j["type"] in ("real_local", "demo", "empty", "tm1_server")


def test_datasource_detect_invalid(client):
    """检测非法目录 → 返回结构化错误。"""
    r = client.post("/api/datasource/detect", json={"path": "Z:/definitely/not/exist"})
    assert r.status_code == 200
    j = r.json()
    assert j["valid"] is False
    assert j["error"]


def test_datasource_detect_missing_path(client):
    """缺 path → 400。"""
    r = client.post("/api/datasource/detect", json={})
    assert r.status_code == 400


def test_datasource_use_demo(client):
    """切换到 demo → ok。"""
    r = client.post("/api/datasource/use", json={"source": "demo"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["status"]["type"] == "demo"


def test_datasource_use_unknown(client):
    """未知 source → 400。"""
    r = client.post("/api/datasource/use", json={"source": "nonsense"})
    assert r.status_code == 400


def test_datasource_use_local_invalid(client):
    """切换到无效本地目录 → 400。"""
    r = client.post("/api/datasource/use", json={"source": "local", "path": "Z:/nope"})
    assert r.status_code == 400


def test_exact_database_file_survives_restart(client, tmp_path):
    import os
    import subprocess
    from test_datasource import _make_real_db
    original = _make_real_db(tmp_path / "selected")
    chosen = original.with_name("custom-model.duckdb")
    original.rename(chosen)
    response = client.post("/api/datasource/use", json={"source":"local", "path":str(chosen)})
    assert response.status_code == 200
    assert Path(response.json()["status"]["db_path"]) == chosen
    environment = os.environ.copy()
    environment["TM1_INSIGHT_HOME"] = str(tmp_path)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.check_output([sys.executable, "-c", "from tm1_insight.config import get_settings; print(get_settings().db_path)"],
                                     env=environment, text=True)
    assert Path(result.strip()) == chosen


def test_import_is_atomic_and_never_overwrites_demo_or_active_model(client, tmp_path):
    import hashlib
    from test_datasource import _make_real_db
    client.post("/api/datasource/use", json={"source":"demo"})
    previous = Path(client.get("/api/datasource/status").json()["db_path"])
    digest = hashlib.sha256(previous.read_bytes()).hexdigest()
    source = _make_real_db(tmp_path / "upload-fixture")
    response = client.post("/api/import", files={"file":("model.duckdb", source.read_bytes(), "application/octet-stream")})
    assert response.status_code == 200
    assert response.json()["status"]["type"] == "real_local"
    imported = Path(response.json()["db_path"])
    assert imported != previous
    assert hashlib.sha256(previous.read_bytes()).hexdigest() == digest
    failed = client.post("/api/import", files={"file":("invalid.duckdb", b"not-a-database", "application/octet-stream")})
    assert failed.status_code == 400
    assert Path(client.get("/api/datasource/status").json()["db_path"]) == imported


def test_zip_import_accepts_one_arbitrary_filename_and_rejects_ambiguous_models(client, tmp_path):
    import io
    import zipfile
    from test_datasource import _make_real_db
    model = _make_real_db(tmp_path / "zip-fixture").read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../custom-model.duckdb", model)
    response = client.post("/api/import", files={"file":("model.zip", buffer.getvalue(), "application/zip")})
    assert response.status_code == 200
    selected = response.json()["db_path"]
    assert Path(selected).is_relative_to(tmp_path / "imports")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data/db/tm1_insight.duckdb", model)
        archive.writestr("other.duckdb", model)
    response = client.post("/api/import", files={"file":("models.zip", buffer.getvalue(), "application/zip")})
    assert response.status_code == 400
    assert client.get("/api/datasource/status").json()["db_path"] == selected


def test_knowledge_background_result_pagination_export_and_source_isolation(client, tmp_path):
    import io
    import time
    import zipfile
    from test_datasource import _make_real_db
    assert client.post("/api/knowledge/tasks", json={"prefix":""}).status_code == 400
    client.get("/")
    created = client.post("/api/knowledge/tasks", json={"prefix":"Load"})
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    deadline = time.monotonic() + 5
    while True:
        state = client.get(f"/api/knowledge/tasks/{task_id}").json()
        if state["status"] not in {"queued", "running"}:
            break
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert state["status"] == "completed"
    response = client.get(f"/api/knowledge/tasks/{task_id}/result?limit=1")
    assert response.status_code == 200
    assert len(response.json()["items"]) <= 1
    assert not response.json()["privacy"]["contains_source"]
    export = client.post(f"/api/knowledge/tasks/{task_id}/export", json={"context_type":"process", "name":"Load_Sales"})
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        package = json.loads(archive.read("development_context.json"))
        assert [p["process"] for p in package["processes"]] == ["Load_Sales"]
        assert "source_code" not in package["processes"][0]
    _make_real_db(tmp_path / "other-model")
    assert client.post("/api/datasource/use", json={"source":"local", "path":str(tmp_path / "other-model")}).status_code == 200
    assert client.get(f"/api/knowledge/tasks/{task_id}/result").status_code == 409
