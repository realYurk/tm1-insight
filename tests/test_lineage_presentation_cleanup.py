from pathlib import Path

ROOT = Path('src/tm1_insight/api')


def test_unwanted_ui_is_hidden_but_legacy_capabilities_remain():
    base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
    lineage = (ROOT / 'templates/cube_lineage.html').read_text(encoding='utf-8')
    cube = (ROOT / 'templates/cube_view.html').read_text(encoding='utf-8')
    assert '<details hidden class="nav-advanced"' in base
    assert 'id="cl-advanced" class="cl-advanced" hidden' in lineage
    assert 'id="cube-formation"' not in cube
    assert (ROOT / 'static/cube-formation.js').exists()
    assert '/api/trace?' in (ROOT / 'static/home.js').read_text(encoding='utf-8')


def test_object_badges_are_shared_across_search_entry_points():
    for file in ('static/home.js', 'static/lineage-search.js', 'static/architecture.js', 'templates/impact.html'):
        assert 'TM1ObjectBadge' in (ROOT / file).read_text(encoding='utf-8')
    assert 'object-badge.js' in (ROOT / 'templates/base.html').read_text(encoding='utf-8')
