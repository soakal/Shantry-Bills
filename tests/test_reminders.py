import smtplib
import sqlite3
from datetime import date

import pytest


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


def test_cron_reminders_flags_overdue_bill_as_overdue(client, monkeypatch):
    import app as flask_app

    if date.today().day == 1:
        pytest.skip("no valid overdue due_day when today is the 1st of the month")

    conn = sqlite3.connect(flask_app.DB_PATH)
    conn.execute(
        "INSERT INTO bills (name, amount, due_day, notes, icon, active) "
        "VALUES (?, ?, ?, '', '', 1)",
        ("Overdue Test Bill", 99.0, date.today().day - 1),
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
            sendmail_calls.append(msg)

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 200
    assert len(sendmail_calls) == 1
    assert "OVERDUE" in sendmail_calls[0]
    assert "Overdue Test Bill" in sendmail_calls[0]


def test_cron_reminders_sends_to_multiple_recipients(client, monkeypatch):
    import app as flask_app

    _insert_due_soon_bill(flask_app.DB_PATH)

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    # deliberate space after the comma -- exercises the .strip()
    monkeypatch.setattr(
        flask_app, "JON_SMS_GATEWAY", "1234567890@example.com, 9876543210@example.com"
    )

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
            return {}  # empty dict == no recipients refused

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["sms_sent"] is True
    assert len(sendmail_calls) == 1
    _, to_addrs, _ = sendmail_calls[0]
    assert to_addrs == ["1234567890@example.com", "9876543210@example.com"]


def test_cron_reminders_reports_error_on_partial_recipient_refusal(client, monkeypatch):
    import app as flask_app

    _insert_due_soon_bill(flask_app.DB_PATH)

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    monkeypatch.setattr(
        flask_app, "JON_SMS_GATEWAY", "good@example.com,bad@example.com"
    )

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
            # smtplib returns a dict of refused addresses on PARTIAL failure
            # (it only raises when ALL recipients are refused)
            return {"bad@example.com": (550, b"mailbox unavailable")}

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 502
    data = response.get_json()
    assert data["sms_sent"] is False
    assert "bad@example.com" in data["error"]


def test_cron_reminders_comma_only_gateway_treated_as_unconfigured(client, monkeypatch):
    import app as flask_app

    _insert_due_soon_bill(flask_app.DB_PATH)

    monkeypatch.setattr(flask_app, "CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(flask_app, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(flask_app, "SMTP_PASS", "password")
    monkeypatch.setattr(flask_app, "JON_SMS_GATEWAY", " , ")

    response = client.post(
        "/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
    )

    assert response.status_code == 503
    data = response.get_json()
    assert data["error"] == "SMTP not configured"


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
