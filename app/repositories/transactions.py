from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountTransaction


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        kind: str,
        amount_microrub: int,
        balance_after_microrub: int,
        description: str,
        device_id: int | None = None,
        payment_id: int | None = None,
    ) -> AccountTransaction:
        transaction = AccountTransaction(
            user_id=user_id,
            device_id=device_id,
            payment_id=payment_id,
            kind=kind,
            amount_microrub=amount_microrub,
            balance_after_microrub=balance_after_microrub,
            description=description,
        )
        self.session.add(transaction)
        await self.session.flush()
        return transaction

    async def list_for_user(self, user_id: int, *, limit: int = 100) -> list[AccountTransaction]:
        result = await self.session.execute(
            select(AccountTransaction)
            .where(AccountTransaction.user_id == user_id)
            .order_by(AccountTransaction.created_at.desc(), AccountTransaction.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

