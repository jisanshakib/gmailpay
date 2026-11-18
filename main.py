"""
main.py — Combined entrypoint: FastAPI backend + Aiogram Telegram bot.
Runs both in a single process for Railway deployment.
"""

import asyncio
import logging
import sys

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

import config
import db
from bot_client import api as bot_api_client
from routes import bot_router, admin_router, owner_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Bot setup (lazy — router attached once inside _setup_dispatcher)
# ---------------------------------------------------------------------------
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
_dp_ready = False          # guard: attach router exactly once


def _setup_dispatcher():
    """Attach handlers and middleware to the dispatcher exactly once."""
    global _dp_ready
    if _dp_ready:
        return
    _dp_ready = True

    from handlers import router as handlers_router
    from middleware import BanCheckMiddleware, RateLimitMiddleware, AutoRegisterMiddleware

    # Middleware (order: auto-register → ban-check → rate-limit)
    dp.message.middleware(AutoRegisterMiddleware())
    dp.callback_query.middleware(AutoRegisterMiddleware())
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())

    # Handlers — only once
    dp.include_router(handlers_router)
    logger.info("Dispatcher ready: middleware + handlers attached.")


# ---------------------------------------------------------------------------
#  FastAPI lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup/shutdown events."""
    # -- startup --
    logger.info("Initializing databases…")
    db.init_databases()

    logger.info("Setting up bot dispatcher…")
    _setup_dispatcher()

    logger.info("Starting bot API client…")
    await bot_api_client.start()

    if config.WEBHOOK_URL:
        webhook_url = f"{config.WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info("Setting webhook: %s", webhook_url)
        await bot.set_webhook(
            url=webhook_url,
            secret_token=config.WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        logger.info("No WEBHOOK_URL set — starting long-polling in background…")
        asyncio.create_task(_run_polling())

    yield

    # -- shutdown --
    logger.info("Shutting down…")
    if config.WEBHOOK_URL:
        try:
            await bot.delete_webhook()
        except Exception:
            pass
    await bot_api_client.close()
    await bot.session.close()


async def _run_polling():
    """Run bot polling as background asyncio task."""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Polling error: %s", exc)


# ---------------------------------------------------------------------------
#  FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Gmail Bot API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(bot_router)
app.include_router(admin_router)
app.include_router(owner_router)


# ---------------------------------------------------------------------------
#  Webhook endpoint
# ---------------------------------------------------------------------------
@app.post("/webhook")
async def webhook_handler(request: Request) -> Response:
    """Receive Telegram updates via webhook."""
    if config.WEBHOOK_SECRET:
        header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_token != config.WEBHOOK_SECRET:
            return Response(status_code=403)

    body = await request.body()
    update = Update.model_validate_raw(body)
    await dp.feed_update(bot=bot, update=update)
    return Response(status_code=200)


# ---------------------------------------------------------------------------
#  Health check
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok", "bot": bool(config.BOT_TOKEN)}


@app.get("/")
def root():
    return {"service": "Gmail Bot API", "version": "1.0.0", "status": "running"}


# ---------------------------------------------------------------------------
#  Run — pass app object directly, NOT string, to avoid re-import
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = config.PORT
    logger.info("Starting server on port %d", port)
    _setup_dispatcher()       # ensure router attached before uvicorn starts
    uvicorn.run(
        app,                  # pass app object directly — no re-import!
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
