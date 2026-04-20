from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.models import Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return await self.session.get(Payment, payment_id)

    async def get_by_provider_payment_id(self, provider: str, provider_payment_id: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        provider: str,
        provider_payment_id: str,
        amount: Decimal,
        currency: str,
        plan_code: str,
        subscription_days: int,
        raw_payload: dict | None = None,
    ) -> Payment:
        payment = Payment(
            user_id=user_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            currency=currency,
            plan_code=plan_code,
            subscription_days=subscription_days,
            raw_payload=raw_payload or {},
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def mark_paid(self, payment: Payment, *, raw_payload: dict | None = None, paid_at: datetime | None = None) -> Payment:
        payment.status = "paid"
        payment.paid_at = paid_at or utcnow()
        if raw_payload is not None:
            payment.raw_payload = raw_payload
        await self.session.flush()
        return payment

    async def mark_failed(self, payment: Payment, *, raw_payload: dict | None = None) -> Payment:
        payment.status = "failed"
        if raw_payload is not None:
            payment.raw_payload = raw_payload
        await self.session.flush()
        return payment

    async def list_for_user(self, user_id: int, *, limit: int = 50) -> list[Payment]:
        result = await self.session.execute(
            select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Payment]:
        result = await self.session.execute(select(Payment).order_by(Payment.created_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())

