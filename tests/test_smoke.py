def test_login_page_returns_200(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_unauthenticated_root_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
