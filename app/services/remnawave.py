from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.security import utcnow


class RemnawaveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemnawaveUser:
    uuid: str
    raw: dict


class RemnawaveClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def add_user(self, *, username: str, days: int, traffic_limit_bytes: int) -> RemnawaveUser:
        if self.settings.REMNA_MOCK_MODE or not self.settings.REMNA_TOKEN:
            user_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"remnawave:{username}"))
            return RemnawaveUser(uuid=user_uuid, raw={"uuid": user_uuid, "mock": True})

        expire_at = (utcnow() + timedelta(days=days)).isoformat()
        payload = {
            "username": username,
            "days": days,
            "trafficLimitBytes": traffic_limit_bytes,
            "expireAt": expire_at,
            "status": "ACTIVE",
        }
        data = await self._request("POST", "/api/users", json=payload)
        user_uuid = data.get("uuid") or data.get("id") or data.get("userUuid")
        if not user_uuid:
            raise RemnawaveError("Remnawave response does not contain user UUID")
        return RemnawaveUser(uuid=str(user_uuid), raw=data)

    async def extend_user(self, *, remnawave_uuid: str, days: int, traffic_limit_bytes: int | None = None) -> None:
        if self.settings.REMNA_MOCK_MODE or not self.settings.REMNA_TOKEN:
            return

        payload: dict[str, int] = {"days": days}
        if traffic_limit_bytes is not None:
            payload["trafficLimitBytes"] = traffic_limit_bytes
        await self._request("PATCH", f"/api/users/{remnawave_uuid}", json=payload)

    async def get_user_usage(self, remnawave_uuid: str) -> dict:
        if self.settings.REMNA_MOCK_MODE or not self.settings.REMNA_TOKEN:
            return {"trafficUsedBytes": 0}
        return await self._request("GET", f"/api/users/{remnawave_uuid}")

    async def get_vless_config(self, *, remnawave_uuid: str, email: str) -> str:
        if self.settings.REMNA_MOCK_MODE or not self.settings.REMNA_TOKEN:
            tag = quote(email)
            return f"vless://{remnawave_uuid}@example.com:443?type=tcp&security=tls#{tag}"

        path = self.settings.REMNA_SUBSCRIPTION_PATH_TEMPLATE.format(uuid=remnawave_uuid)
        text = await self._request_text("GET", path)
        return text.strip()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        data = await self._request_text(method, path, **kwargs)
        try:
            return json.loads(data)
        except ValueError as exc:
            raise RemnawaveError("Remnawave returned invalid JSON") from exc

    async def _request_text(self, method: str, path: str, **kwargs) -> str:
        url = f"{self.settings.REMNA_BASE_URL.rstrip('/')}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.settings.REMNA_TOKEN}"

        last_error: Exception | None = None
        for attempt in range(self.settings.REMNA_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.REMNA_TIMEOUT_SECONDS) as client:
                    response = await client.request(method, url, headers=headers, **kwargs)
                    response.raise_for_status()
                    return response.text
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt >= self.settings.REMNA_RETRIES:
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RemnawaveError(f"Remnawave request failed: {last_error}") from last_error
