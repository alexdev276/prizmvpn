from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, User
from tests.fakes import FakeEmailService, FakeRemnawaveClient


async def test_register_and_login_without_email_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_email: FakeEmailService,
    fake_remna: FakeRemnawaveClient,
) -> None:
    response = await client.post(
        "/register",
        data={"email": "person@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?registered=1&email=person%40example.com"
    assert fake_email.verification_tokens == []
    assert fake_remna.created == []

    result = await db_session.execute(select(User).where(User.email == "person@example.com"))
    user = result.scalar_one()
    assert user.is_verified is True
    assert user.remnawave_uuid is None

    login_response = await client.post(
        "/login",
        data={"email": "person@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/account"
    assert "prizm_session" in login_response.cookies

    add_device_response = await client.post("/account/devices", follow_redirects=False)
    assert add_device_response.status_code == 303
    assert len(fake_remna.created) == 1
    assert fake_remna.created[0]["username"].startswith("person-example-com-")

    device_result = await db_session.execute(select(Device).where(Device.user_id == user.id))
    device = device_result.scalar_one()
    assert device.remnawave_uuid == "remna-1"

    config_response = await client.get(f"/subscription/{device.public_id}/{device.config_uuid}.txt")
    assert config_response.status_code == 200
    assert "vless://remna-1@example.com:443" in config_response.text


async def test_password_reset_flow(
    client: AsyncClient,
    fake_email: FakeEmailService,
) -> None:
    await client.post("/register", data={"email": "reset@example.com", "password": "password123"})

    response = await client.post("/forgot-password", data={"email": "reset@example.com"})
    assert response.status_code == 200
    assert len(fake_email.reset_tokens) == 1

    _, reset_token = fake_email.reset_tokens[0]
    reset_response = await client.post(
        "/reset-password",
        data={"token": reset_token, "password": "newpassword123"},
    )
    assert reset_response.status_code == 200

    login_response = await client.post(
        "/login",
        data={"email": "reset@example.com", "password": "newpassword123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
