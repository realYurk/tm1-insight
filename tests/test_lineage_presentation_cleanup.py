from pathlib import Path

ROOT = Path('src/tm1_insight/api')


def test_unwanted_ui_is_hidden_but_legacy_capabilities_remain():
    base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
    lineage = (ROOT / 'templates/_cube_lineage_body.html').read_text(encoding='utf-8')
    cube = (ROOT / 'templates/cube_view.html').read_text(encoding='utf-8')
    assert 'nav-advanced' not in base  # 高级工具入口已下线，旧路由仍可直达
    assert '<details class="cl-advanced"' in lineage  # 高级导出默认折叠，不占首屏
    assert 'id="cube-formation"' not in cube
    assert (ROOT / 'static/cube-formation.js').exists()
    assert '/api/trace?' in (ROOT / 'static/home.js').read_text(encoding='utf-8')


def test_object_badges_are_shared_across_search_entry_points():
    for file in ('static/home.js', 'static/lineage-search.js', 'static/architecture.js', 'templates/impact.html'):
        assert 'TM1ObjectBadge' in (ROOT / file).read_text(encoding='utf-8')
    assert 'object-badge.js' in (ROOT / 'templates/base.html').read_text(encoding='utf-8')
