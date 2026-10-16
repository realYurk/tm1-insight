"""Workbench 1.1 版本信息可见化测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tm1_insight.api.app import app


def test_build_info_shape():
    from tm1_insight.buildinfo import build_info

    info = build_info()
    assert set(info) == {"version", "git_sha", "build_time", "packaged", "mode"}
    assert info["version"]
    assert info["mode"] in ("source", "portable")
    assert info["packaged"] is False  # 测试环境一定是源码模式


def test_build_info_injected_into_home():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "sidebar-version" in r.text
    # 源码模式应标注「开发版」，而非 Portable
    assert "开发版" in r.text


def test_settings_page_shows_version():
    c = TestClient(app)
    r = c.get("/settings")
    assert r.status_code == 200
    assert "关于 / 版本信息" in r.text
    assert "Git 提交" in r.text
    assert "运行模式" in r.text


def test_no_sensitive_info_leaked():
    """版本信息不暴露密码 / Token / 完整私有数据路径。"""
    from tm1_insight.buildinfo import build_info

    info = build_info()
    blob = repr(info)
    assert "password" not in blob.lower()
    assert "token" not in blob.lower()
