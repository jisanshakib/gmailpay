"""
bot_client.py — Async HTTP client for bot → backend API communication.
"""

import asyncio
import logging
from typing import Any, Optional
import aiohttp
import config

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, status: int, detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__(f"API {status}: {detail}")


class APIClient:
    def __init__(self):
        self._base = config.API_BASE_URL.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT)
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def _request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        if not self._session:
            await self.start()
        url = f"{self._base}{path}"
        for attempt in range(3):
            try:
                async with self._session.request(method, url, json=json, params=params) as resp:
                    body = await resp.json() if resp.content_type == "application/json" else {}
                    if resp.status >= 400:
                        detail = body.get("detail", "") if isinstance(body, dict) else str(body)
                        raise APIError(resp.status, detail)
                    return body
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    logger.warning("Retry %d for %s %s: %s", attempt + 1, method, path, exc)
                else:
                    raise

    # --- Public methods ---
    async def register_user(self, telegram_id: int, username: str = "") -> dict:
        return await self._request("POST", "/api/bot/register-user",
                                   json={"telegram_id": telegram_id, "username": username})

    async def get_settings(self) -> dict:
        return await self._request("GET", "/api/bot/settings")

    async def get_user_info(self, telegram_id: int) -> dict:
        return await self._request("GET", f"/api/bot/user-info/{telegram_id}")

    async def get_balance(self, telegram_id: int) -> dict:
        return await self._request("GET", f"/api/bot/balance/{telegram_id}")

    async def assign_task(self, telegram_id: int) -> dict:
        return await self._request("GET", f"/api/bot/assign-task/{telegram_id}")

    async def submit_account(self, telegram_id: int, submission_type: str,
                             email: str, password: str,
                             secret_key_2fa: str = None,
                             recovery_email: str = None) -> dict:
        payload = {"telegram_id": telegram_id, "submission_type": submission_type,
                    "email": email, "password": password}
        if secret_key_2fa:
            payload["secret_key_2fa"] = secret_key_2fa
        if recovery_email:
            payload["recovery_email"] = recovery_email
        return await self._request("POST", "/api/bot/submit", json=payload)

    async def request_withdrawal(self, telegram_id: int, method: str,
                                 wallet_or_number: str, amount: float) -> dict:
        return await self._request("POST", "/api/bot/withdraw-request",
                                   json={"telegram_id": telegram_id, "method": method,
                                          "wallet_or_number": wallet_or_number, "amount": amount})

    async def check_ban(self, telegram_id: int) -> bool:
        try:
            info = await self.get_user_info(telegram_id)
            return bool(info.get("is_banned", False))
        except APIError:
            return False


api = APIClient()
