from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, utcnow
from app.models import User
from app.repositories.transactions import TransactionRepository
from app.services.account import AccountError, AccountService
from app.services.money import DEVICE_HOURLY_PRICE_MICRORUB, rub_to_microrub
from tests.fakes import FakeRemnawaveClient


async def test_device_billing_and_delete_lock(db_session: AsyncSession) -> None:
    user = User(
        email="device@example.com",
        hashed_password=hash_password("password123"),
        is_verified=True,
        balance_microrub=rub_to_microrub(100),
    )
    db_session.add(user)
    await db_session.flush()

    fake_remna = FakeRemnawaveClient()
    service = AccountService(db_session, settings, fake_remna)
    device = await service.add_device(user, title="IPhone 16")

    assert device.remnawave_uuid == "remna-1"
    assert fake_remna.created[0]["username"].startswith("device-example-com-")
    assert fake_remna.created[0]["traffic_limit_bytes"] == settings.REMNA_TRAFFIC_LIMIT_BYTES

    with pytest.raises(AccountError):
        await service.delete_device(user, device.id)

    device.last_billed_at = utcnow() - timedelta(hours=2, minutes=5)
    await db_session.flush()

    charged = await service.bill_user_devices(user)

    assert charged == DEVICE_HOURLY_PRICE_MICRORUB * 2
    assert user.balance_microrub == rub_to_microrub(100) - charged

    transactions = await TransactionRepository(db_session).list_for_user(user.id)
    assert any(transaction.kind == "device_charge" for transaction in transactions)
