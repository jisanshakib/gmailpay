"""
middleware.py — Aiogram middleware: ban-check (cached), rate-limit, auto-register.
"""

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot_client import api, APIError
import config

logger = logging.getLogger(__name__)

_ban_cache: Dict[int, tuple] = {}
_rate_cache: Dict[int, float] = {}
_registered: set = set()


def _get_tg_id(event: TelegramObject):
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return event.from_user.id
    return None


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable, event: TelegramObject, data: Dict[str, Any]) -> Any:
        tg_id = _get_tg_id(event)
        if tg_id is None:
            return await handler(event, data)

        now = time.monotonic()
        cached = _ban_cache.get(tg_id)
        if cached and cached[1] > now:
            is_banned = cached[0]
        else:
            try:
                is_banned = await api.check_ban(tg_id)
            except Exception:
                is_banned = False
            _ban_cache[tg_id] = (is_banned, now + config.BAN_CACHE_TTL)

        if is_banned:
            if isinstance(event, Message):
                await event.answer("🚫 <b>Your account has been banned.</b>\nContact support if you believe this is an error.", parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 You are banned.", show_alert=True)
            return
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable, event: TelegramObject, data: Dict[str, Any]) -> Any:
        tg_id = _get_tg_id(event)
        if tg_id is None:
            return await handler(event, data)
        now = time.monotonic()
        last = _rate_cache.get(tg_id, 0.0)
        if now - last < config.RATE_LIMIT_SECONDS:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Slow down.", show_alert=False)
            return
        _rate_cache[tg_id] = now
        return await handler(event, data)


class AutoRegisterMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable, event: TelegramObject, data: Dict[str, Any]) -> Any:
        tg_id = _get_tg_id(event)
        if tg_id and tg_id not in _registered:
            username = None
            if isinstance(event, (Message, CallbackQuery)) and event.from_user:
                username = event.from_user.username
            try:
                await api.register_user(tg_id, username or "")
                _registered.add(tg_id)
            except Exception as exc:
                logger.warning("Auto-register failed for %s: %s", tg_id, exc)
        return await handler(event, data)
