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
                 "/impact", "/compare", "/audit", "/codegen", "/settings"]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


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
