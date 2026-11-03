"""P0：左侧导航永久展开的合成测试。

验证 base.html 已从 <details>/<summary> 改为静态导航结构：
- 无 .nav-group details / .nav-chevron 折叠箭头
- 模型浏览保持可见；Human-First 2.0 将低频工具折叠，旧路由全部保留
- navigation.js 不再读写 tm1-nav-group-* 折叠偏好（改为清理）
"""
from __future__ import annotations

from pathlib import Path

import pytest


BASE = Path(__file__).resolve().parents[1] / "src" / "tm1_insight" / "api"
BASE_HTML = BASE / "templates" / "base.html"
NAV_JS = BASE / "static" / "navigation.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_base_html_has_no_collapsible_nav_group():
    html = _read(BASE_HTML)
    # 不再使用 details/summary 做折叠分组，也不再有折叠箭头
    assert '<details class="nav-group"' not in html
    assert 'nav-chevron' not in html
    assert 'nav-group-summary' not in html


def test_base_html_nav_entries_all_retained():
    html = _read(BASE_HTML)
    # 一级入口收敛为四个；对象详情从 /object 进入，不再为每类对象各开一页。
    for href, label in [
        ("/", "工作台"),
        ("/atlas", "资产地图"),
        ("/object", "对象工作台"),
        ("/browse", "模型目录"),
        ("/audit", "前端资产"),
        ("/settings", "连接设置"),
    ]:
        assert href in html, f"导航缺少 {label} ({href})"
        assert label in html, f"导航缺少标签 {label}"
    # 合并后的旧入口不再占用导航位置。
    for gone in ("/graph", "/architecture", "/codegen", "/impact", "/compare"):
        assert gone not in html, f"旧入口仍在一级导航：{gone}"


def test_nav_group_labels_present():
    html = _read(BASE_HTML)
    assert '数据与设置' in html
    assert '高级工具' not in html
    assert '模型浏览' not in html


def test_navigation_js_clears_stale_preferences_not_saves():
    js = _read(NAV_JS)
    # 不再保存折叠偏好，改为清理历史遗留的 tm1-nav-group-* 键
    assert "tm1-nav-group-" in js
    assert "removeItem" in js
    # 不应对 .nav-group 做展开/收起状态读写（已移除）
    assert "group.open" not in js
    assert "querySelectorAll('.nav-group')" not in js
