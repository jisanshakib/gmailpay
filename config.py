"""
config.py — All configuration loaded from environment variables.
Single Supabase PostgreSQL database.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Supabase PostgreSQL ---
# Standard connection string: postgresql://user:pass@host:port/dbname
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# --- Telegram Bot ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")          # Leave empty for polling mode
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")     # Optional webhook secret

# --- JWT / Security ---
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

# --- API ---
PORT = int(os.environ.get("PORT", "8000"))
API_BASE_URL = os.environ.get("API_BASE_URL", f"http://127.0.0.1:{PORT}")

# --- Bot Behaviour ---
API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "15"))
RATE_LIMIT_SECONDS = float(os.environ.get("RATE_LIMIT_SECONDS", "1.0"))
BAN_CACHE_TTL = int(os.environ.get("BAN_CACHE_TTL", "30"))
