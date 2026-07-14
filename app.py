import logging
import os
import sqlite3
import sys
from calendar import monthrange
from datetime import date
from functools import wraps
from logging.handlers import RotatingFileHandler

from flask import Flask, abort, g, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-change-me")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
DB_PATH = os.environ.get("DB_PATH", "bills.db")

# Logs to stdout (captured by `fly logs`, short retention) AND a rotating file
# on the same persisted volume as the DB (survives restarts, longer retention
# we control). So a "the reminder didn't show up Tuesday" report is traceable
# without needing the customer to send anything themselves.
LOG_PATH = os.environ.get("LOG_PATH", os.path.join(os.path.dirname(DB_PATH) or ".", "app.log"))
_log_format = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

# Accessing app.logger for the first time auto-attaches Flask's own default
# handler (bracketed format, to stderr); clear it first so our two handlers
# below are the only ones -- otherwise every line prints twice.
app.logger.handlers.clear()

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_log_format)
app.logger.addHandler(_stream_handler)

_file_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)
_file_handler.setFormatter(_log_format)
app.logger.addHandler(_file_handler)

app.logger.setLevel(logging.INFO)

CRON_SECRET = os.environ.get("CRON_SECRET", "")
REMINDER_DAYS_BEFORE = int(os.environ.get("REMINDER_DAYS_BEFORE", "3"))
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
JON_SMS_GATEWAY = os.environ.get("JON_SMS_GATEWAY")  # comma-separated for multiple recipients
# Where in-app "Report a problem" submissions go. Defaults to the sending Gmail's
# own inbox (SMTP_USER) so no extra config is needed; override with SUPPORT_EMAIL.
# Must be a REAL mailbox, not an SMS gateway -- gateways strip the log attachment.
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL") or SMTP_USER


# ---------- DB ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def log_request(response):
    app.logger.info(
        "%s %s -> %s (%s)",
        request.method,
        request.path,
        response.status_code,
        request.remote_addr,
    )
    return response


COMMON_ICONS = [
    ("", "No icon"),
    ("💧", "Water"),
    ("⚡", "Electric"),
    ("🏠", "Rent / Mortgage"),
    ("🚗", "Auto"),
    ("📱", "Phone"),
    ("📶", "Internet"),
    ("🔥", "Gas / Heat"),
    ("💳", "Credit Card"),
    ("🛡️", "Insurance"),
    ("🗑️", "Trash / Utilities"),
    ("🐾", "Pet"),
    ("🧾", "Other"),
]


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_day INTEGER NOT NULL CHECK(due_day BETWEEN 1 AND 31),
            notes TEXT DEFAULT '',
            icon TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
            period TEXT NOT NULL,
            paid_date TEXT,
            amount_paid REAL,
            UNIQUE(bill_id, period)
        );
        """
    )
    # migration path for databases created before the icon column existed
    existing_cols = {row[1] for row in db.execute("PRAGMA table_info(bills)").fetchall()}
    if "icon" not in existing_cols:
        db.execute("ALTER TABLE bills ADD COLUMN icon TEXT DEFAULT ''")
    db.commit()
    db.close()


# ---------- PWA ----------

@app.route("/sw.js")
def service_worker():
    # Served at root (not /static/sw.js) so iOS Safari gives it scope "/" --
    # WebKit's default service worker scope is the directory it's served
    # from, and a /static/-scoped worker could never control app pages.
    response = app.send_static_file("sw.js")
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- Auth ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            session.permanent = True
            app.logger.info("login: success from %s", request.remote_addr)
            return redirect(request.args.get("next") or url_for("index"))
        error = "Wrong password."
        app.logger.warning("login: failed attempt from %s", request.remote_addr)
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Helpers ----------

def normalize_period(raw: str | None) -> str:
    """Return `raw` if it's a valid YYYY-MM string, otherwise fall back to
    the current period. Guards `due_date_for`/`shift_period` (which do
    `map(int, period.split("-"))` with no validation) against malformed
    or missing `?month=` query values."""
    if raw:
        parts = raw.split("-")
        if len(parts) == 2:
            year_str, month_str = parts
            if year_str.isdigit() and month_str.isdigit():
                month = int(month_str)
                if 1 <= month <= 12:
                    return raw
    return date.today().strftime("%Y-%m")


def due_date_for(period: str, due_day: int) -> date:
    year, month = map(int, period.split("-"))
    last_day = monthrange(year, month)[1]
    return date(year, month, min(due_day, last_day))


def shift_period(period: str, delta_months: int) -> str:
    year, month = map(int, period.split("-"))
    month += delta_months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


# ---------- Routes ----------

@app.route("/")
@login_required
def index():
    period = normalize_period(request.args.get("month"))
    db = get_db()
    bills = db.execute(
        "SELECT * FROM bills WHERE active = 1 ORDER BY due_day"
    ).fetchall()
    payments = {
        row["bill_id"]: row
        for row in db.execute(
            "SELECT * FROM payments WHERE period = ?", (period,)
        ).fetchall()
    }

    today = date.today()
    rows = []
    total = 0.0
    total_paid = 0.0
    for bill in bills:
        due = due_date_for(period, bill["due_day"])
        paid = bill["id"] in payments
        rows.append(
            {
                "bill": bill,
                "due_date": due,
                "paid": paid,
                "overdue": (not paid) and due < today,
            }
        )
        total += bill["amount"]
        if paid:
            total_paid += bill["amount"]

    rows.sort(key=lambda r: r["due_date"])

    year, month = map(int, period.split("-"))
    period_display = date(year, month, 1).strftime("%B %Y")

    return render_template(
        "index.html",
        rows=rows,
        period=period,
        period_display=period_display,
        prev_period=shift_period(period, -1),
        next_period=shift_period(period, 1),
        total=total,
        total_paid=total_paid,
        remaining=total - total_paid,
    )


@app.route("/toggle/<int:bill_id>", methods=["POST"])
@login_required
def toggle(bill_id):
    period = request.form["period"]
    db = get_db()
    existing = db.execute(
        "SELECT id FROM payments WHERE bill_id = ? AND period = ?",
        (bill_id, period),
    ).fetchone()
    if existing:
        db.execute("DELETE FROM payments WHERE id = ?", (existing["id"],))
    else:
        bill = db.execute("SELECT amount FROM bills WHERE id = ?", (bill_id,)).fetchone()
        db.execute(
            "INSERT INTO payments (bill_id, period, paid_date, amount_paid) VALUES (?, ?, ?, ?)",
            (bill_id, period, date.today().isoformat(), bill["amount"]),
        )
    db.commit()
    return redirect(url_for("index", month=period))


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_bill():
    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO bills (name, amount, due_day, notes, icon) VALUES (?, ?, ?, ?, ?)",
            (
                request.form["name"].strip(),
                float(request.form["amount"]),
                int(request.form["due_day"]),
                request.form.get("notes", "").strip(),
                request.form.get("icon", "").strip(),
            ),
        )
        db.commit()
        return redirect(url_for("index"))
    return render_template("bill_form.html", bill=None, icons=COMMON_ICONS)


@app.route("/edit/<int:bill_id>", methods=["GET", "POST"])
@login_required
def edit_bill(bill_id):
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if request.method == "POST":
        db.execute(
            "UPDATE bills SET name = ?, amount = ?, due_day = ?, notes = ?, icon = ? WHERE id = ?",
            (
                request.form["name"].strip(),
                float(request.form["amount"]),
                int(request.form["due_day"]),
                request.form.get("notes", "").strip(),
                request.form.get("icon", "").strip(),
                bill_id,
            ),
        )
        db.commit()
        return redirect(url_for("index"))
    return render_template("bill_form.html", bill=bill, icons=COMMON_ICONS)


@app.route("/delete/<int:bill_id>", methods=["POST"])
@login_required
def delete_bill(bill_id):
    db = get_db()
    db.execute("UPDATE bills SET active = 0 WHERE id = ?", (bill_id,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/support", methods=["POST"])
@login_required
def support():
    """In-app 'Report a problem' button. Emails SUPPORT_EMAIL the reporter's
    note plus the current log file (attached) and its last 40 lines inline, so
    a problem can be diagnosed without the user having to find/send anything."""
    reporter_note = request.form.get("message", "").strip()

    if not (SMTP_USER and SMTP_PASS and SUPPORT_EMAIL):
        app.logger.warning("support: report submitted but SMTP/SUPPORT_EMAIL not configured")
        return redirect(url_for("index", support="unconfigured"))

    log_tail = "(log file not readable)"
    log_bytes = b""
    try:
        with open(LOG_PATH, "rb") as fh:
            log_bytes = fh.read()
        log_tail = "\n".join(log_bytes.decode("utf-8", "replace").splitlines()[-40:])
    except OSError:
        pass

    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    body = (
        "Shantry Bills problem report\n"
        f"When: {date.today().isoformat()}\n"
        f"From IP: {request.remote_addr}\n"
        f"Browser: {request.headers.get('User-Agent', '?')}\n\n"
        f"Message:\n{reporter_note or '(no message entered)'}\n\n"
        f"--- last 40 log lines ---\n{log_tail}\n"
    )

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = SUPPORT_EMAIL
    msg["Subject"] = "Shantry Bills - problem report"
    msg.attach(MIMEText(body))
    if log_bytes:
        attachment = MIMEApplication(log_bytes, Name="app.log")
        attachment["Content-Disposition"] = 'attachment; filename="app.log"'
        msg.attach(attachment)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [SUPPORT_EMAIL], msg.as_string())
        app.logger.info("support: report sent to %s", SUPPORT_EMAIL)
        return redirect(url_for("index", support="sent"))
    except Exception:
        app.logger.exception("support: failed to send report")
        return redirect(url_for("index", support="failed"))


@app.route("/cron/reminders", methods=["POST"])
def send_reminders():
    if not CRON_SECRET or request.headers.get("X-Cron-Secret") != CRON_SECRET:
        abort(403)

    db = get_db()
    today = date.today()
    current_period = today.strftime("%Y-%m")
    next_period = shift_period(current_period, 1)

    bills = db.execute("SELECT * FROM bills WHERE active = 1").fetchall()

    due_soon = []
    for period in (current_period, next_period):
        paid_ids = {
            row["bill_id"]
            for row in db.execute(
                "SELECT bill_id FROM payments WHERE period = ?", (period,)
            ).fetchall()
        }
        for bill in bills:
            if bill["id"] in paid_ids:
                continue
            due = due_date_for(period, bill["due_day"])
            days_out = (due - today).days
            if days_out <= REMINDER_DAYS_BEFORE:
                due_soon.append((bill, due))
    due_soon.sort(key=lambda item: (item[1] - today).days)

    recipients = [addr.strip() for addr in (JON_SMS_GATEWAY or "").split(",") if addr.strip()]

    sent = False
    error = None
    if due_soon and not (SMTP_USER and SMTP_PASS and recipients):
        app.logger.warning("reminders: %d due but SMTP not configured", len(due_soon))
        return {
            "due_soon": len(due_soon),
            "sms_sent": False,
            "error": "SMTP not configured",
        }, 503

    if due_soon and SMTP_USER and SMTP_PASS and recipients:
        import smtplib
        from email.mime.text import MIMEText

        lines = [
            f"{'OVERDUE' if (due - today).days < 0 else 'Due'} "
            f"{b['icon']+' ' if b['icon'] else ''}{b['name']} ${b['amount']:.2f} {due.strftime('%b %d')}"
            for b, due in due_soon
        ]
        msg = MIMEText("Bills due soon:\n" + "\n".join(lines))
        msg["From"] = SMTP_USER
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = ""  # most carrier gateways drop the subject line anyway

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                refused = server.sendmail(SMTP_USER, recipients, msg.as_string())
            if refused:
                error = f"some recipients refused: {refused}"
            else:
                sent = True
        except Exception as exc:
            error = str(exc)
            app.logger.exception("reminders: failed to send SMS")

    if error is not None:
        app.logger.error("reminders: due_soon=%d sent=%s error=%s", len(due_soon), sent, error)
        return {"due_soon": len(due_soon), "sms_sent": sent, "error": error}, 502

    app.logger.info("reminders: due_soon=%d sent=%s", len(due_soon), sent)
    return {"due_soon": len(due_soon), "sms_sent": sent}, 200


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
