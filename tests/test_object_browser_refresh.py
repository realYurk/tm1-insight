from test_datasource_api import client  # noqa: F401


def test_object_landing_pages_are_lists_without_automatic_detail(client):
    for path, label in [('/cubes', 'Cube 详情'), ('/dimensions', '维度详情')]:
        response = client.get(path)
        assert response.status_code == 200
        assert f'aria-label="{label}" hidden' in response.text
        assert 'data-open-object-switcher' not in response.text


def test_legacy_tool_routes_remain_available_without_nav_entries(client):
    html = client.get('/').text
    assert 'aria-label="工程资产"' not in html
    assert 'aria-label="可配置分摊"' not in html
    assert client.get('/assets').status_code == 200
    assert client.get('/allocation').status_code == 200
