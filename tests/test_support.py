import smtplib


def _login(client):
    client.post("/login", data={"password": "test-password"})


def test_support_requires_login(client):
    with client.session_transaction() as sess:
        sess.clear()
    response = client.post("/support", data={"message": "help"}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_support_sends_email_with_log_attachment(client, monkeypatch):
    import app as flask_app

    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    monkeypatch.setattr(flask_app, "SUPPORT_EMAIL", "brian@example.com")

    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, from_addr, to_addrs, msg):
            sent.append((from_addr, to_addrs, msg))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    _login(client)
    response = client.post(
        "/support", data={"message": "the reminder never came"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert "support=sent" in response.headers["Location"]
    assert len(sent) == 1
    from_addr, to_addrs, msg = sent[0]
    assert to_addrs == ["brian@example.com"]
    assert "the reminder never came" in msg
    assert 'filename="app.log"' in msg  # log file attached


def test_support_unconfigured_redirects_gracefully(client, monkeypatch):
    import app as flask_app

    monkeypatch.setattr(flask_app, "SMTP_USER", None)
    monkeypatch.setattr(flask_app, "SMTP_PASS", None)
    monkeypatch.setattr(flask_app, "SUPPORT_EMAIL", None)

    _login(client)
    response = client.post("/support", data={"message": "x"}, follow_redirects=False)
    assert response.status_code == 302
    assert "support=unconfigured" in response.headers["Location"]
