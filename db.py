"""SQLite storage. One file, no server, trivially portable to any host."""
import json
import sqlite3
import secrets
from datetime import datetime, timezone

import config
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    product_name TEXT,
    supplier_details TEXT,
    notes TEXT,
    marketing_optin INTEGER DEFAULT 0,
    calc_inputs TEXT,
    calc_results TEXT,
    summary TEXT,
    source TEXT,
    token TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    lead_id INTEGER,
    reference TEXT UNIQUE,
    service TEXT,
    amount_gbp REAL,
    status TEXT,               -- pending | paid | cancelled
    provider TEXT,             -- stripe | paypal | demo | manual
    provider_ref TEXT,
    paid_at TEXT,
    questionnaire TEXT,
    questionnaire_at TEXT,
    report_status TEXT,        -- none | auto | manual_review | delivered
    report_html TEXT,
    report_notes TEXT,
    report_updated_at TEXT,
    token TEXT UNIQUE,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    to_addr TEXT,
    subject TEXT,
    body TEXT,
    kind TEXT,
    status TEXT,               -- sent | queued | failed
    error TEXT
);
CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT, email TEXT, phone TEXT, message TEXT, service TEXT
);
CREATE TABLE IF NOT EXISTS sequence_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    step INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL,      -- scheduled | sent | cancelled
    sent_at TEXT,
    email_id INTEGER,
    UNIQUE(lead_id, step),
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_seq_due ON sequence_jobs(status, due_at);
"""

# Columns added after the first release. Applied on every start so an existing
# database upgrades in place without losing anything.
MIGRATIONS = [
    ("leads", "unsubscribed", "ALTER TABLE leads ADD COLUMN unsubscribed INTEGER DEFAULT 0"),
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            if column not in cols:
                conn.execute(ddl)


def token():
    return secrets.token_urlsafe(18)


def reference():
    """Customer-facing order reference, e.g. SR-260810-9F3A1C."""
    stamp = datetime.now(timezone.utc).strftime("%y%m%d")
    return "%s-%s-%s" % (config.ORDER_PREFIX, stamp, secrets.token_hex(3).upper())


# --- leads -----------------------------------------------------------------
def create_lead(data, calc_inputs, calc_results, summary, source="calculator"):
    tok = token()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO leads (created_at, name, email, phone, product_name,
               supplier_details, notes, marketing_optin, calc_inputs, calc_results,
               summary, source, token)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now(), data.get("name"), data.get("email"), data.get("phone"),
             data.get("product_name"), data.get("supplier_details"), data.get("notes"),
             1 if data.get("marketing_optin") else 0,
             json.dumps(calc_inputs), json.dumps(calc_results), summary, source, tok),
        )
        return cur.lastrowid, tok


def get_lead(lead_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()


def get_lead_by_token(tok):
    with connect() as conn:
        return conn.execute("SELECT * FROM leads WHERE token=?", (tok,)).fetchone()


def list_leads(limit=500):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


# --- orders ----------------------------------------------------------------
def create_order(lead_id, service, amount, provider):
    ref, tok = reference(), token()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO orders (created_at, lead_id, reference, service, amount_gbp,
               status, provider, report_status, token)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (now(), lead_id, ref, service, amount, "pending", provider, "none", tok),
        )
        return cur.lastrowid, ref, tok


def get_order(order_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


def get_order_by_token(tok):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE token=?", (tok,)).fetchone()


def get_order_by_ref(ref):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()


def get_order_by_provider_ref(pref):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE provider_ref=?", (pref,)).fetchone()


def set_provider_ref(order_id, provider, pref):
    with connect() as conn:
        conn.execute("UPDATE orders SET provider=?, provider_ref=? WHERE id=?",
                     (provider, pref, order_id))


def mark_paid(order_id):
    with connect() as conn:
        conn.execute("UPDATE orders SET status='paid', paid_at=? WHERE id=?", (now(), order_id))


def save_questionnaire(order_id, payload):
    with connect() as conn:
        conn.execute("UPDATE orders SET questionnaire=?, questionnaire_at=? WHERE id=?",
                     (json.dumps(payload), now(), order_id))


def save_report(order_id, html, status, notes=None):
    with connect() as conn:
        if notes is None:
            conn.execute(
                "UPDATE orders SET report_html=?, report_status=?, report_updated_at=? WHERE id=?",
                (html, status, now(), order_id))
        else:
            conn.execute(
                """UPDATE orders SET report_html=?, report_status=?, report_notes=?,
                   report_updated_at=? WHERE id=?""",
                (html, status, notes, now(), order_id))


def list_orders(limit=500):
    with connect() as conn:
        return conn.execute(
            """SELECT o.*, l.name AS lead_name, l.email AS lead_email
               FROM orders o LEFT JOIN leads l ON l.id = o.lead_id
               ORDER BY o.id DESC LIMIT ?""", (limit,)).fetchall()


# --- emails ----------------------------------------------------------------
def log_email(to_addr, subject, body, kind, status, error=None):
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO emails (created_at, to_addr, subject, body, kind, status, error)
               VALUES (?,?,?,?,?,?,?)""",
            (now(), to_addr, subject, body, kind, status, error))
        return cur.lastrowid


def list_emails(limit=300):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM emails ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def get_email(email_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()


# --- enquiries -------------------------------------------------------------
def create_enquiry(data):
    with connect() as conn:
        conn.execute(
            """INSERT INTO enquiries (created_at, name, email, phone, message, service)
               VALUES (?,?,?,?,?,?)""",
            (now(), data.get("name"), data.get("email"), data.get("phone"),
             data.get("message"), data.get("service")))


def list_enquiries(limit=300):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM enquiries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


# --- email sequence --------------------------------------------------------
def schedule_sequence(lead_id, due_map):
    """due_map: {step: iso_due_at}. Ignores steps already scheduled or sent."""
    with connect() as conn:
        for step, due_at in due_map.items():
            conn.execute(
                """INSERT OR IGNORE INTO sequence_jobs (lead_id, step, due_at, status)
                   VALUES (?,?,?,'scheduled')""", (lead_id, step, due_at))


def due_sequence_jobs(now_iso, limit=25):
    with connect() as conn:
        return conn.execute(
            """SELECT j.*, l.name, l.email, l.product_name, l.calc_results, l.token,
                      l.unsubscribed
               FROM sequence_jobs j JOIN leads l ON l.id = j.lead_id
               WHERE j.status='scheduled' AND j.due_at <= ?
               ORDER BY j.due_at LIMIT ?""", (now_iso, limit)).fetchall()


def mark_sequence_sent(job_id, email_id):
    with connect() as conn:
        conn.execute(
            "UPDATE sequence_jobs SET status='sent', sent_at=?, email_id=? WHERE id=?",
            (now(), email_id, job_id))


def cancel_sequence(lead_id, reason_status="cancelled"):
    """Stop the nurture once someone has bought or opted out."""
    with connect() as conn:
        conn.execute(
            "UPDATE sequence_jobs SET status=? WHERE lead_id=? AND status='scheduled'",
            (reason_status, lead_id))


def unsubscribe_lead(tok):
    with connect() as conn:
        row = conn.execute("SELECT id FROM leads WHERE token=?", (tok,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE leads SET unsubscribed=1 WHERE id=?", (row["id"],))
        conn.execute(
            "UPDATE sequence_jobs SET status='cancelled' WHERE lead_id=? AND status='scheduled'",
            (row["id"],))
        return row["id"]


def list_sequence_jobs(limit=400):
    with connect() as conn:
        return conn.execute(
            """SELECT j.*, l.name, l.email, l.product_name
               FROM sequence_jobs j JOIN leads l ON l.id = j.lead_id
               ORDER BY j.due_at DESC LIMIT ?""", (limit,)).fetchall()


def stats():
    with connect() as conn:
        one = lambda q: conn.execute(q).fetchone()[0]
        return {
            "leads": one("SELECT COUNT(*) FROM leads"),
            "orders": one("SELECT COUNT(*) FROM orders"),
            "paid": one("SELECT COUNT(*) FROM orders WHERE status='paid'"),
            "revenue": one("SELECT COALESCE(SUM(amount_gbp),0) FROM orders WHERE status='paid'"),
            "awaiting": one("SELECT COUNT(*) FROM orders WHERE status='paid' AND report_status IN ('none','auto','manual_review')"),
            "enquiries": one("SELECT COUNT(*) FROM enquiries"),
            "emails": one("SELECT COUNT(*) FROM emails"),
            "seq_pending": one("SELECT COUNT(*) FROM sequence_jobs WHERE status='scheduled'"),
            "seq_sent": one("SELECT COUNT(*) FROM sequence_jobs WHERE status='sent'"),
        }


def last_payment_error():
    """Most recent failed attempt to start a payment, so a broken gateway is visible."""
    with connect() as conn:
        return conn.execute(
            """SELECT created_at, subject, body FROM emails
               WHERE kind='error' AND subject LIKE 'Payment start failed%'
               ORDER BY id DESC LIMIT 1""").fetchone()
