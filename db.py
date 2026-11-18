"""
db.py — Supabase PostgreSQL Database Connection Layer
Uses psycopg2 (sync) via standard DATABASE_URL.

Single database — both core tables (users, admins, bot_settings, withdrawals)
and gmail tables (recovery_emails, submissions) live together.
"""

import sys
import random
import string
import psycopg2
import psycopg2.extras
import config


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_conn():
    """Create a new psycopg2 connection from DATABASE_URL."""
    url = config.DATABASE_URL
    if not url:
        msg = "[DB] ❌ DATABASE_URL is EMPTY. Set it in Railway env vars."
        print(msg, file=sys.stderr)
        raise RuntimeError(msg)
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# FastAPI dependency — yields a connection, auto-commits or rolls back
# ---------------------------------------------------------------------------

def get_db():
    """FastAPI Depends() — yields conn, commits on success, rolls back on error."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Gmail credential generator — used by assign_task
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "james", "mary", "john", "linda", "robert", "sarah", "michael", "emma",
    "david", "olivia", "daniel", "sophia", "william", "mia", "joseph", "ava",
    "alex", "noah", "lucas", "ethan", "liam", "mason", "aiden", "logan",
    "ella", "chloe", "lily", "zoe", "hannah", "grace", "aria", "riley",
]
_LAST_NAMES = [
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller",
    "davis", "martinez", "anderson", "taylor", "thomas", "moore", "jackson",
    "white", "harris", "clark", "lewis", "robinson", "walker", "hall", "lee",
]


def generate_gmail_credentials():
    """Generate a random gmail address and 12-char password.

    Returns (email, password) tuple.
    Email format: firstname.lastnameXXXX@gmail.com
    Password: 12 random alphanumeric + special chars
    """
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    digits = "".join(random.choices(string.digits, k=random.randint(3, 5)))
    email = f"{first}.{last}{digits}@gmail.com"

    # Generate a strong 12-char password
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    password = "".join(random.choices(chars, k=12))

    return email, password


# ---------------------------------------------------------------------------
# Default settings seed data
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Init — create tables + seed default settings.  Call once at startup.
# ---------------------------------------------------------------------------

def init_database():
    """Create all tables and seed default settings."""
    print("[DB] Connecting to Supabase PostgreSQL ...")
    conn = _get_conn()
    cur = conn.cursor()
    try:
        # --- Core tables ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id            BIGINT PRIMARY KEY,
                username               TEXT,
                main_balance           DOUBLE PRECISION DEFAULT 0.0,
                pending_balance        DOUBLE PRECISION DEFAULT 0.0,
                total_completed_gmails INTEGER DEFAULT 0,
                total_strikes          INTEGER DEFAULT 0,
                is_banned              BOOLEAN DEFAULT FALSE,
                block_until            TIMESTAMPTZ,
                created_at             TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL CHECK(role IN ('owner','admin'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key_name  TEXT PRIMARY KEY,
                key_value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id               SERIAL PRIMARY KEY,
                telegram_id      BIGINT NOT NULL REFERENCES users(telegram_id),
                method           TEXT NOT NULL,
                wallet_or_number TEXT NOT NULL,
                amount           DOUBLE PRECISION NOT NULL,
                status           TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                requested_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # --- Gmail farming tables ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_emails (
                id          SERIAL PRIMARY KEY,
                email       TEXT UNIQUE NOT NULL,
                is_assigned BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id              SERIAL PRIMARY KEY,
                telegram_id     BIGINT NOT NULL REFERENCES users(telegram_id),
                submission_type TEXT NOT NULL CHECK(submission_type IN ('normal','2fa')),
                email           TEXT UNIQUE NOT NULL,
                password        TEXT NOT NULL,
                recovery_email  TEXT,
                secret_key_2fa  TEXT,
                status          TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                submitted_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # --- Seed default settings ---
        cur.execute("SELECT COUNT(*) FROM bot_settings")
        count = cur.fetchone()[0]
        if count == 0:
            for k, v in DEFAULT_SETTINGS.items():
                cur.execute(
                    "INSERT INTO bot_settings (key_name, key_value) VALUES (%s, %s) "
                    "ON CONFLICT (key_name) DO NOTHING",
                    (k, v),
                )

        conn.commit()
        print("[DB] ✅ All tables ready.")
    except Exception as e:
        conn.rollback()
        print(f"[DB] ❌ Database init FAILED: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()
