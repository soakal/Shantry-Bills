from datetime import date


def _login(client):
    with client.session_transaction() as sess:
        sess["authed"] = True


def _logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def test_index_with_malformed_month_falls_back_to_current_period(client):
    _login(client)
    try:
        response = client.get("/?month=garbage")
        assert response.status_code == 200
    finally:
        _logout(client)


def test_index_with_out_of_range_month_falls_back_to_current_period(client):
    _login(client)
    try:
        response = client.get("/?month=2026-13")
        assert response.status_code == 200
    finally:
        _logout(client)


def test_normalize_period_accepts_valid_input_unchanged():
    import app as flask_app

    assert flask_app.normalize_period("2026-07") == "2026-07"


def test_normalize_period_rejects_malformed_input():
    import app as flask_app

    today = date.today().strftime("%Y-%m")
    assert flask_app.normalize_period("garbage") == today
    assert flask_app.normalize_period("2026-13") == today
    assert flask_app.normalize_period(None) == today
    assert flask_app.normalize_period("") == today
