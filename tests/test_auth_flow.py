from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.fakes import FakeEmailService, FakeRemnawaveClient


async def test_register_confirm_and_login(
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
    assert len(fake_email.verification_tokens) == 1

    _, token = fake_email.verification_tokens[0]
    verify_response = await client.get(f"/verify-email?token={token}")
    assert verify_response.status_code == 200
    assert fake_remna.created[0]["username"] == "person@example.com"

    result = await db_session.execute(select(User).where(User.email == "person@example.com"))
    user = result.scalar_one()
    assert user.is_verified is True
    assert user.remnawave_uuid == "remna-1"

    login_response = await client.post(
        "/login",
        data={"email": "person@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert "prizm_session" in login_response.cookies


async def test_password_reset_flow(
    client: AsyncClient,
    fake_email: FakeEmailService,
) -> None:
    await client.post("/register", data={"email": "reset@example.com", "password": "password123"})
    _, verify_token = fake_email.verification_tokens[-1]
    await client.get(f"/verify-email?token={verify_token}")

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
