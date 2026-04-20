from __future__ import annotations

from app.services.remnawave import RemnawaveUser


class FakeEmailService:
    def __init__(self) -> None:
        self.verification_tokens: list[tuple[str, str]] = []
        self.reset_tokens: list[tuple[str, str]] = []

    async def send_verification_email(self, email: str, token: str) -> None:
        self.verification_tokens.append((email, token))

    async def send_password_reset_email(self, email: str, token: str) -> None:
        self.reset_tokens.append((email, token))


class FakeRemnawaveClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.extended: list[dict] = []
        self.disabled: list[str] = []

    async def add_user(self, *, username: str, days: int, traffic_limit_bytes: int) -> RemnawaveUser:
        self.created.append({"username": username, "days": days, "traffic_limit_bytes": traffic_limit_bytes})
        user_id = f"remna-{len(self.created)}"
        subscription_url = f"/api/sub/{user_id}"
        return RemnawaveUser(
            uuid=user_id,
            username=username,
            short_uuid=None,
            subscription_url=subscription_url,
            raw={"uuid": user_id, "username": username, "subscriptionUrl": subscription_url, "mock": True},
        )

    async def extend_user(self, *, remnawave_uuid: str, days: int, traffic_limit_bytes: int | None = None) -> None:
        self.extended.append({"uuid": remnawave_uuid, "days": days, "traffic_limit_bytes": traffic_limit_bytes})

    async def disable_user(self, remnawave_uuid: str) -> None:
        self.disabled.append(remnawave_uuid)

    async def get_user_usage(self, remnawave_uuid: str) -> dict:
        return {"trafficUsedBytes": 1234}

    async def get_vless_config(self, *, remnawave_uuid: str, email: str) -> str:
        return f"vless://{remnawave_uuid}@example.com:443#{email}"

    async def get_subscription(self, subscription_url: str) -> str:
        return f"vless://{subscription_url.rsplit('/', 1)[-1]}@example.com:443#device"
