"""Workbench 1.0 阶段 A：跨页面状态记忆 + Cube 页面重构 的合成测试。

不连接真实 TM1。覆盖：
1. base.html 注入 model_fingerprint（按模型隔离状态记忆的前提）。
2. workbench-context.js 提供版本化、按模型隔离的状态 API（静态检查）。
3. Cube 详情页模板：写入 TI 紧凑列表、搜索框、分页（大结果集）、固定常量高亮。
4. Cube 详情页数据形成/使用与去向区域的中性措辞（不制造确定的数据传输结论）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1] / "src" / "tm1_insight" / "api"
BASE_HTML = BASE / "templates" / "base.html"
CUBE_VIEW = BASE / "templates" / "cube_view.html"
# Workbench 1.1：Cube 详情主体抽取为片段，供双栏页与独立详情页共用
CUBE_DETAIL = BASE / "templates" / "_cube_detail.html"
CTX_JS = BASE / "static" / "workbench-context.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_base_html_injects_model_fingerprint():
    html = _read(BASE_HTML)
    assert 'data-model-fingerprint="{{ model_fingerprint() }}"' in html
    assert 'workbench-context.js' in html


def test_workbench_context_js_versioned_and_model_isolated():
    js = _read(CTX_JS)
    # 版本化：防止旧结构污染新代码
    assert "VERSION" in js
    assert "_v" in js
    # 按模型指纹隔离：session key 拼接指纹
    assert "fingerprint" in js
    assert "SESSION_PREFIX" in js
    # 长期偏好与会话状态分离
    assert "PREF_PREFIX" in js
    # 只存 UI 状态，不写敏感凭据键（不持久化 password/credential/auth 类字段）
    assert "password" not in js.lower()
    assert "credential" not in js.lower()
    assert re.search(r"setItem\(\s*['\"][^'\"]*(pass|cred|auth|token)", js) is None


def test_workbench_context_preferences_use_localstorage():
    """长期偏好必须写 localStorage（跨会话保留），而非 sessionStorage。"""
    js = _read(CTX_JS)
    # preference 读 localStorage
    assert re.search(r"function preference\(key\).*?localStorage\.getItem", js, re.S)
    # setPreference 写 localStorage
    assert re.search(r"function setPreference\(key, value\).*?localStorage\.setItem", js, re.S)
    # 会话状态 get/set 用 sessionStorage
    assert re.search(r"function get\(key\).*?readSession", js, re.S)
    assert re.search(r"sessionStorage\.setItem\(sessionKey", js)


def test_workbench_context_has_jump_source_memory():
    """跨对象跳转来源记忆（rememberJump / recallJump）存在，用于「返回来源 Cube」。"""
    js = _read(CTX_JS)
    assert "rememberJump" in js
    assert "recallJump" in js
    # 列表位置记忆含选中对象
    assert "rememberList" in js
    assert "recallList" in js


def test_cube_view_writer_list_and_search():
    html = _read(CUBE_DETAIL)
    # 紧凑写入 TI 列表 + 搜索 + 数量
    assert 'id="writer-list"' in html
    assert 'id="writer-search"' in html
    assert 'class="writer-row"' in html
    # 大结果集分页（>20 个写入 TI 时显示）
    assert 'id="writer-prev"' in html
    assert 'id="writer-next"' in html


def test_cube_view_fixed_constant_highlight():
    html = _read(CUBE_DETAIL)
    # 固定常量 / 参数 / 变量 三种样式类存在，用于区分高亮
    assert 'class="const-lit"' in html
    assert 'class="param-inline"' in html
    assert 'class="var-local"' in html


def test_cube_view_neutral_lineage_wording():
    html = _read(CUBE_DETAIL)
    # 不制造「值一定由此传输」的确定结论
    assert "不代表值一定由此传输" in html
    assert "相关读取" in html
    # 旧的确定性措辞已移除
    assert "搬运工" not in html
    assert "谁读它" not in html


def test_cube_view_preserves_rules_and_jump_links():
    html = _read(CUBE_DETAIL)
    # Rule 展示保留
    assert 'id="rules"' in html
    assert 'data-highlight="rules"' in html
    # 对象跳转保留（TI / Cube / Dimension）
    assert '/explorer/process/' in html
    assert '/explorer/cube/' in html
    assert '/dimensions?name=' in html
