"""
db.py — Turso SQLite Dual Database Connection Layer
Database 1 (core_db): Users, Admins, Finances, Settings
Database 2 (gmail_db): Gmail Pool, Submissions
"""

import os
import libsql_experimental as libsql

# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------

def get_core_db():
    return libsql.connect(
        database=os.environ["TURSO_CORE_DB_URL"],
        auth_token=os.environ["TURSO_CORE_DB_TOKEN"],
    )

def get_gmail_db():
    return libsql.connect(
        database=os.environ["TURSO_GMAIL_DB_URL"],
        auth_token=os.environ["TURSO_GMAIL_DB_TOKEN"],
    )

# FastAPI dependencies (yield + close)
def core_db_dep():
    db = get_core_db()
    try:
        yield db
    finally:
        db.close()

def gmail_db_dep():
    db = get_gmail_db()
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CORE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        telegram_id            INTEGER PRIMARY KEY,
        username               TEXT,
        main_balance           REAL    DEFAULT 0.0,
        pending_balance        REAL    DEFAULT 0.0,
        total_completed_gmails INTEGER DEFAULT 0,
        total_strikes          INTEGER DEFAULT 0,
        is_banned              INTEGER DEFAULT 0,
        block_until            TEXT,
        created_at             TEXT    DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS admins (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT    UNIQUE NOT NULL,
        password_hash TEXT    NOT NULL,
        role          TEXT    NOT NULL CHECK(role IN ('owner','admin'))
    )""",
    """CREATE TABLE IF NOT EXISTS bot_settings (
        key_name  TEXT PRIMARY KEY,
        key_value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS withdrawals (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id      INTEGER NOT NULL,
        method           TEXT    NOT NULL,
        wallet_or_number TEXT    NOT NULL,
        amount           REAL   NOT NULL,
        status           TEXT   DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        requested_at     TEXT   DEFAULT (datetime('now'))
    )""",
]

GMAIL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS gmail_pool (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        email          TEXT    UNIQUE NOT NULL,
        password       TEXT    NOT NULL,
        recovery_email TEXT,
        is_assigned    INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS submissions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER NOT NULL,
        submission_type TEXT    NOT NULL CHECK(submission_type IN ('normal','2fa')),
        email           TEXT    UNIQUE NOT NULL,
        password        TEXT    NOT NULL,
        secret_key_2fa  TEXT,
        status          TEXT    DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        submitted_at    TEXT    DEFAULT (datetime('now'))
    )""",
]

DEFAULT_SETTINGS = {
    "banner_image_url": "",
    "bot_description": "Welcome to Gmail Bot! Complete tasks and earn rewards.",
    "news_channel": "",
    "support_username": "",
    "normal_rate": "0.30",
    "two_fa_rate": "0.50",
    "ref_bonus": "0.10",
    "min_withdrawal": "5.00",
}


def init_databases():
    """Create all tables and seed default settings. Call once at startup."""
    core = get_core_db()
    for stmt in CORE_SCHEMA:
        core.execute(stmt)
    existing = core.execute("SELECT COUNT(*) FROM bot_settings").fetchone()[0]
    if existing == 0:
        for k, v in DEFAULT_SETTINGS.items():
            core.execute("INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES (?, ?)", (k, v))
    core.commit()
    core.close()

    gmail = get_gmail_db()
    for stmt in GMAIL_SCHEMA:
        gmail.execute(stmt)
    gmail.commit()
    gmail.close()
    print("[DB] Both databases initialised.")
