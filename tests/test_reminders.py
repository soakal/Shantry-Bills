import smtplib
import sqlite3
from datetime import date


def _insert_due_soon_bill(db_path):
    """Insert a bill whose due date is today, so it always lands in due_soon
    for the current period regardless of REMINDER_DAYS_BEFORE's default."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO bills (name, amount, due_day, notes, icon, active) "
        "VALUES (?, ?, ?, '', '', 1)",
        ("Test Reminder Bill", 42.0, date.today().day),
    )
    conn.commit()
    conn.close()


def test_cron_reminders_returns_502_on_smtp_failure(client, monkeypatch):
    import app as flask_app

    _insert_due_soon_bill(flask_app.DB_PATH)

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    monkeypatch.setattr(flask_app, "JON_SMS_GATEWAY", "1234567890@example.com")

    class RaisingSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPConnectError(421, "simulated SMTP outage")

    monkeypatch.setattr(smtplib, "SMTP", RaisingSMTP)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 502
    data = response.get_json()
    assert data["sms_sent"] is False
    assert "error" in data
    assert data["due_soon"] >= 1


def test_cron_reminders_sends_sms_on_success(client, monkeypatch):
    import app as flask_app

    conn = sqlite3.connect(flask_app.DB_PATH)
    conn.execute(
        "INSERT INTO bills (name, amount, due_day, notes, icon, active) "
        "VALUES (?, ?, ?, '', '', 1)",
        ("Reminder Success Bill", 17.5, date.today().day),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    monkeypatch.setattr(flask_app, "JON_SMS_GATEWAY", "1234567890@example.com")

    sendmail_calls = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, from_addr, to_addrs, msg):
            sendmail_calls.append((from_addr, to_addrs, msg))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["sms_sent"] is True
    assert data["due_soon"] >= 1
    assert len(sendmail_calls) == 1


def test_cron_reminders_returns_503_when_smtp_not_configured(client, monkeypatch):
    import app as flask_app

    _insert_due_soon_bill(flask_app.DB_PATH)

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", None)
    monkeypatch.setattr(flask_app, "SMTP_PASS", None)
    monkeypatch.setattr(flask_app, "JON_SMS_GATEWAY", None)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 503
    data = response.get_json()
    assert data["sms_sent"] is False
    assert data["error"] == "SMTP not configured"
    assert data["due_soon"] >= 1
