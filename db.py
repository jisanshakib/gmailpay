"""
db.py — Turso SQLite Dual Database Connection Layer
Uses libsql_client (pure Python, works on Railway/Linux).
Provides a compatibility wrapper so routes.py works unchanged.

Database 1 (core_db): Users, Admins, Finances, Settings
Database 2 (gmail_db): Gmail Pool, Submissions
"""

import os
import libsql_client


# ---------------------------------------------------------------------------
# Compatibility wrapper — same interface as libsql_experimental
# so routes.py .execute().fetchone() / .fetchall() / .commit() all work
# ---------------------------------------------------------------------------

class _ResultProxy:
    """Wraps libsql_client ResultSet to provide fetchone/fetchall."""
    def __init__(self, rs):
        self._rows = [tuple(row) for row in rs.rows] if rs and rs.rows else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __getitem__(self, idx):
        return self._rows[idx]

    def __len__(self):
        return len(self._rows)


class _DBConnection:
    """Wraps libsql_client sync client to match the old libsql_experimental API."""

    def __init__(self, url: str, auth_token: str):
        self._client = libsql_client.create_client_sync(
            url=url,
            auth_token=auth_token,
        )

    def execute(self, sql: str, params=None):
        if params is not None:
            if isinstance(params, (list, tuple)):
                rs = self._client.execute(sql, params)
            else:
                rs = self._client.execute(sql, [params])
        else:
            rs = self._client.execute(sql)
        return _ResultProxy(rs)

    def commit(self):
        # libsql_client HTTP mode auto-commits each statement
        pass

    def close(self):
        self._client.close()


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------

def get_core_db():
    return _DBConnection(
        url=os.environ["TURSO_CORE_DB_URL"],
        auth_token=os.environ["TURSO_CORE_DB_TOKEN"],
    )

def get_gmail_db():
    return _DBConnection(
        url=os.environ["TURSO_GMAIL_DB_URL"],
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
    core.close()

    gmail = get_gmail_db()
    for stmt in GMAIL_SCHEMA:
        gmail.execute(stmt)
    gmail.close()
    print("[DB] Both databases initialised.")
