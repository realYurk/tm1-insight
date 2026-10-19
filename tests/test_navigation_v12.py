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
    # 所有核心入口必须存在（模型资产 + 高级工具 + 系统与数据）
    for href, label in [
        ("/", "工作台"),
        ("/cubes", "Cube"),
        ("/dimensions", "Dimension"),
        ("/processes", "TI 进程"),
        ("/chores", "Chore 调度"),
        ("/codegen", "代码生成"),
        ("/graph", "数据血缘"),
        ("/architecture", "业务架构"),
        ("/impact", "影响分析"),
        ("/compare", "快照与版本"),
        ("/audit", "前端资产"),
        ("/workflow", "工作流技术检查"),
        ("/knowledge", "证据包导出"),
        ("/learn", "功能梳理（旧版）"),
        ("/experience", "我的经验"),
        ("/settings", "连接设置"),
    ]:
        assert href in html, f"导航缺少 {label} ({href})"
        assert label in html, f"导航缺少标签 {label}"


def test_nav_group_labels_present():
    html = _read(BASE_HTML)
    assert '模型浏览' in html
    assert '高级工具' in html
    assert '模型管理' in html


def test_navigation_js_clears_stale_preferences_not_saves():
    js = _read(NAV_JS)
    # 不再保存折叠偏好，改为清理历史遗留的 tm1-nav-group-* 键
    assert "tm1-nav-group-" in js
    assert "removeItem" in js
    # 不应对 .nav-group 做展开/收起状态读写（已移除）
    assert "group.open" not in js
    assert "querySelectorAll('.nav-group')" not in js
