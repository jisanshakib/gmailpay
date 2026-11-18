"""
config.py — All configuration loaded from environment variables.
Supports multiple env-var naming conventions for Turso.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Turso Databases (accept multiple naming conventions) ---
TURSO_CORE_DB_URL = (
    os.environ.get("TURSO_CORE_DB_URL")
    or os.environ.get("TURSO_CORE_DATABASE_URL")
    or ""
)
TURSO_CORE_DB_TOKEN = (
    os.environ.get("TURSO_CORE_DB_TOKEN")
    or os.environ.get("TURSO_CORE_AUTH_TOKEN")
    or ""
)
TURSO_GMAIL_DB_URL = (
    os.environ.get("TURSO_GMAIL_DB_URL")
    or os.environ.get("TURSO_GMAIL_DATABASE_URL")
    or ""
)
TURSO_GMAIL_DB_TOKEN = (
    os.environ.get("TURSO_GMAIL_DB_TOKEN")
    or os.environ.get("TURSO_GMAIL_AUTH_TOKEN")
    or ""
)

# --- Telegram Bot ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")          # Leave empty for polling mode
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")     # Optional webhook secret

# --- JWT / Security ---
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

# --- API ---
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
PORT = int(os.environ.get("PORT", "8000"))

# --- Bot Behaviour ---
API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "15"))
RATE_LIMIT_SECONDS = float(os.environ.get("RATE_LIMIT_SECONDS", "1.0"))
BAN_CACHE_TTL = int(os.environ.get("BAN_CACHE_TTL", "30"))
