import json


def test_manifest_has_icons(client):
    response = client.get("/static/manifest.json")
    assert response.status_code == 200
    data = json.loads(response.data)
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_service_worker_served_at_root(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.content_type


def test_login_page_has_ios_meta_tags(client):
    response = client.get("/login")
    html = response.data.decode()
    assert "apple-touch-icon" in html
    assert "apple-mobile-web-app-capable" in html
    assert 'rel="manifest"' in html
