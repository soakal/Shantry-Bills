def _logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def test_login_with_correct_password_redirects_to_index_and_authenticates(client):
    try:
        response = client.post(
            "/login", data={"password": "test-password"}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")

        with client.session_transaction() as sess:
            assert sess.get("authed") is True
    finally:
        _logout(client)


def test_login_with_wrong_password_shows_error(client):
    _logout(client)
    try:
        response = client.post(
            "/login", data={"password": "definitely-not-it"}, follow_redirects=False
        )
        assert response.status_code == 200
        assert b"Wrong password." in response.data

        with client.session_transaction() as sess:
            assert not sess.get("authed")
    finally:
        _logout(client)


def test_authenticated_add_bill_persists_and_is_visible_on_index(client):
    login_response = client.post(
        "/login", data={"password": "test-password"}, follow_redirects=False
    )
    assert login_response.status_code == 302
    try:
        bill_name = "Council Test Bill XYZ"
        add_response = client.post(
            "/add",
            data={
                "name": bill_name,
                "amount": "42.50",
                "due_day": "15",
                "notes": "",
                "icon": "",
            },
            follow_redirects=False,
        )
        assert add_response.status_code == 302

        index_response = client.get("/")
        assert index_response.status_code == 200
        assert bill_name.encode() in index_response.data
    finally:
        _logout(client)
