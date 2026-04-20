from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import User
from app.repositories.payments import PaymentRepository
from app.services.money import rub_to_microrub
from app.services.payments import PaymentError, PaymentService
from tests.fakes import FakeRemnawaveClient


def test_cryptocloud_hmac_validation() -> None:
    payload = {"invoice_id": "inv_1", "status": "paid"}
    canonical = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
    signature = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()

    PaymentService._validate_hmac_signature(payload, signature, "secret")
    with pytest.raises(PaymentError):
        PaymentService._validate_hmac_signature(payload, "bad", "secret")


async def test_yookassa_webhook_extends_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_remna: FakeRemnawaveClient,
) -> None:
    user = User(
        email="paid@example.com",
        hashed_password=hash_password("password123"),
        is_verified=True,
        remnawave_uuid="remna-paid",
        traffic_limit_bytes=0,
    )
    db_session.add(user)
    await db_session.flush()

    payment = await PaymentRepository(db_session).create(
        user_id=user.id,
        provider="yookassa",
        provider_payment_id="pay_1",
        amount=Decimal("199.00"),
        currency="RUB",
        plan_code="month",
        subscription_days=30,
    )
    await db_session.commit()

    response = await client.post(
        "/payments/webhooks/yookassa",
        json={"event": "payment.succeeded", "object": {"id": payment.provider_payment_id, "status": "succeeded"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "payment_found": True}
    assert payment.status == "paid"
    assert user.subscription_end is not None
    assert fake_remna.extended == [{"uuid": "remna-paid", "days": 30, "traffic_limit_bytes": 107374182400}]


async def test_test_topup_adds_balance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = User(
        email="topup@example.com",
        hashed_password=hash_password("password123"),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    payment = await PaymentRepository(db_session).create(
        user_id=user.id,
        provider="yookassa",
        provider_payment_id="topup_1",
        amount=Decimal("150.00"),
        currency="RUB",
        plan_code="balance",
        subscription_days=0,
    )
    await db_session.commit()

    response = await client.get(
        f"/payments/test/success?provider=yookassa&id={payment.provider_payment_id}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/account"
    assert payment.status == "paid"
    assert user.balance_microrub == rub_to_microrub(Decimal("150.00"))
