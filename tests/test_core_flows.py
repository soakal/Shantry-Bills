import os
import sqlite3
from datetime import date


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


def test_toggle_marks_bill_paid_then_unpays_on_second_toggle(client):
    login_response = client.post(
        "/login", data={"password": "test-password"}, follow_redirects=False
    )
    assert login_response.status_code == 302
    try:
        bill_name = "Council Test Bill Toggle"
        add_response = client.post(
            "/add",
            data={
                "name": bill_name,
                "amount": "10.00",
                "due_day": "1",
                "notes": "",
                "icon": "",
            },
            follow_redirects=False,
        )
        assert add_response.status_code == 302

        conn = sqlite3.connect(os.environ["DB_PATH"])
        bill_id = conn.execute(
            "SELECT id FROM bills WHERE name = ?", (bill_name,)
        ).fetchone()[0]
        conn.close()

        period = date.today().strftime("%Y-%m")

        toggle_response = client.post(
            f"/toggle/{bill_id}", data={"period": period}, follow_redirects=False
        )
        assert toggle_response.status_code == 302

        conn = sqlite3.connect(os.environ["DB_PATH"])
        payment = conn.execute(
            "SELECT id FROM payments WHERE bill_id = ? AND period = ?",
            (bill_id, period),
        ).fetchone()
        conn.close()
        assert payment is not None

        index_response = client.get("/")
        assert index_response.status_code == 200
        page = index_response.data.decode()
        name_index = page.index(bill_name)
        li_start = page.rindex("<li ", 0, name_index)
        li_end = page.index(">", li_start)
        li_tag = page[li_start:li_end]
        assert "paid" in li_tag.split('"')[1].split()

        toggle_again_response = client.post(
            f"/toggle/{bill_id}", data={"period": period}, follow_redirects=False
        )
        assert toggle_again_response.status_code == 302

        conn = sqlite3.connect(os.environ["DB_PATH"])
        payment_after = conn.execute(
            "SELECT id FROM payments WHERE bill_id = ? AND period = ?",
            (bill_id, period),
        ).fetchone()
        conn.close()
        assert payment_after is None
    finally:
        _logout(client)


def test_delete_soft_deletes_bill_and_removes_from_index(client):
    login_response = client.post(
        "/login", data={"password": "test-password"}, follow_redirects=False
    )
    assert login_response.status_code == 302
    try:
        bill_name = "Council Test Bill Delete"
        add_response = client.post(
            "/add",
            data={
                "name": bill_name,
                "amount": "5.00",
                "due_day": "10",
                "notes": "",
                "icon": "",
            },
            follow_redirects=False,
        )
        assert add_response.status_code == 302

        conn = sqlite3.connect(os.environ["DB_PATH"])
        bill_id = conn.execute(
            "SELECT id FROM bills WHERE name = ?", (bill_name,)
        ).fetchone()[0]
        conn.close()

        index_before = client.get("/")
        assert bill_name.encode() in index_before.data

        delete_response = client.post(
            f"/delete/{bill_id}", follow_redirects=False
        )
        assert delete_response.status_code == 302

        conn = sqlite3.connect(os.environ["DB_PATH"])
        active = conn.execute(
            "SELECT active FROM bills WHERE id = ?", (bill_id,)
        ).fetchone()[0]
        conn.close()
        assert active == 0

        index_after = client.get("/")
        assert bill_name.encode() not in index_after.data
    finally:
        _logout(client)
