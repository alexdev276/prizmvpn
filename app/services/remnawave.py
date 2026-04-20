from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.security import as_utc, utcnow


logger = logging.getLogger(__name__)


class RemnawaveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemnawaveUser:
    uuid: str
    username: str
    short_uuid: str | None
    subscription_url: str | None
    raw: dict


class RemnawaveClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def add_user(self, *, username: str, days: int, traffic_limit_bytes: int) -> RemnawaveUser:
        if self.settings.REMNA_MOCK_MODE:
            user_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"remnawave:{username}"))
            subscription_url = self.settings.REMNA_SUBSCRIPTION_PATH_TEMPLATE.format(uuid=user_uuid)
            return RemnawaveUser(
                uuid=user_uuid,
                username=username,
                short_uuid=None,
                subscription_url=subscription_url,
                raw={"uuid": user_uuid, "username": username, "subscriptionUrl": subscription_url, "mock": True},
            )

        expire_at = self._format_remna_datetime(utcnow() + timedelta(days=days))
        payload = {
            "username": username,
            "trafficLimitBytes": traffic_limit_bytes,
            "expireAt": expire_at,
            "status": "ACTIVE",
        }
        data = self._response_payload(await self._request("POST", "/api/users", json=payload))
        user_uuid = data.get("uuid") or data.get("id") or data.get("userUuid")
        if not user_uuid:
            raise RemnawaveError("Remnawave response does not contain user UUID")
        short_uuid = data.get("shortUuid") or data.get("short_uuid")
        subscription_url = self._extract_subscription_url(data)
        if not subscription_url:
            subscription_url = self.settings.REMNA_SUBSCRIPTION_PATH_TEMPLATE.format(uuid=short_uuid or user_uuid)
        return RemnawaveUser(
            uuid=str(user_uuid),
            username=str(data.get("username") or username),
            short_uuid=str(short_uuid) if short_uuid else None,
            subscription_url=subscription_url,
            raw=data,
        )

    async def extend_user(self, *, remnawave_uuid: str, days: int, traffic_limit_bytes: int | None = None) -> None:
        if self.settings.REMNA_MOCK_MODE:
            return

        user = self._response_payload(await self._request("GET", f"/api/users/{remnawave_uuid}"))
        base = self._parse_remna_datetime(user.get("expireAt") or user.get("expire_at"))
        if not base or base < utcnow():
            base = utcnow()

        payload: dict[str, int | str] = {
            "uuid": remnawave_uuid,
            "expireAt": self._format_remna_datetime(base + timedelta(days=days)),
        }
        if traffic_limit_bytes is not None:
            payload["trafficLimitBytes"] = traffic_limit_bytes
        await self._request("PATCH", "/api/users", json=payload)

    async def disable_user(self, remnawave_uuid: str) -> None:
        if self.settings.REMNA_MOCK_MODE:
            return
        await self._request("POST", f"/api/users/{remnawave_uuid}/actions/disable")

    async def get_user_usage(self, remnawave_uuid: str) -> dict:
        if self.settings.REMNA_MOCK_MODE:
            return {"trafficUsedBytes": 0}
        return self._response_payload(await self._request("GET", f"/api/users/{remnawave_uuid}"))

    async def get_vless_config(self, *, remnawave_uuid: str, email: str) -> str:
        if self.settings.REMNA_MOCK_MODE:
            tag = quote(email)
            return f"vless://{remnawave_uuid}@example.com:443?type=tcp&security=tls#{tag}"

        path = self.settings.REMNA_SUBSCRIPTION_PATH_TEMPLATE.format(uuid=remnawave_uuid)
        text = await self._request_text("GET", path)
        return text.strip()

    async def get_subscription(self, subscription_url: str) -> str:
        if self.settings.REMNA_MOCK_MODE:
            tag = quote(subscription_url.rsplit("/", 1)[-1] or "device")
            return f"vless://{tag}@example.com:443?type=tcp&security=tls#{tag}"
        if subscription_url.startswith(("http://", "https://")):
            try:
                async with httpx.AsyncClient(timeout=self.settings.REMNA_TIMEOUT_SECONDS) as client:
                    response = await client.get(subscription_url)
                    response.raise_for_status()
                    return response.text.strip()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                raise RemnawaveError(f"Remnawave subscription request failed: {exc}") from exc
        return (await self._request_text("GET", subscription_url)).strip()

    @staticmethod
    def _extract_subscription_url(data: dict) -> str | None:
        for key in ("subscriptionUrl", "subscription_url", "subUrl", "sub_url"):
            value = data.get(key)
            if value:
                return str(value)
        subscription = data.get("subscription")
        if isinstance(subscription, dict):
            for key in ("url", "subscriptionUrl", "subscription_url"):
                value = subscription.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _response_payload(data: dict) -> dict:
        response = data.get("response")
        return response if isinstance(response, dict) else data

    @staticmethod
    def _format_remna_datetime(value: datetime) -> str:
        return as_utc(value).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_remna_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            return as_utc(datetime.fromisoformat(normalized))
        except ValueError:
            return None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        data = await self._request_text(method, path, **kwargs)
        try:
            return json.loads(data)
        except ValueError as exc:
            raise RemnawaveError("Remnawave returned invalid JSON") from exc

    async def _request_text(self, method: str, path: str, **kwargs) -> str:
        if not self.settings.REMNA_TOKEN:
            raise RemnawaveError("REMNA_TOKEN is required when REMNA_MOCK_MODE=false")
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
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:1000]
                logger.warning(
                    "Remnawave %s %s failed with HTTP %s: %s",
                    method,
                    path,
                    exc.response.status_code,
                    body,
                )
                last_error = RemnawaveError(
                    f"Remnawave {method} {path} returned HTTP {exc.response.status_code}: {body}"
                )
                break
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt >= self.settings.REMNA_RETRIES:
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RemnawaveError(f"Remnawave request failed: {last_error}") from last_error
