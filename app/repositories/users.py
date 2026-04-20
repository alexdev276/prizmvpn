from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import as_utc, utcnow
from app.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_verification_token_hash(self, token_hash: str) -> User | None:
        result = await self.session.execute(select(User).where(User.verification_token_hash == token_hash))
        return result.scalar_one_or_none()

    async def get_by_reset_token_hash(self, token_hash: str) -> User | None:
        result = await self.session.execute(select(User).where(User.reset_token_hash == token_hash))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        hashed_password: str,
        verification_token_hash: str | None = None,
        verification_token_expires: datetime | None = None,
        is_verified: bool = False,
        is_admin: bool = False,
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hashed_password,
            verification_token_hash=verification_token_hash,
            verification_token_expires=verification_token_expires,
            is_verified=is_verified,
            is_admin=is_admin,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def refresh_verification(
        self,
        user: User,
        *,
        hashed_password: str,
        token_hash: str,
        expires_at: datetime,
    ) -> User:
        user.hashed_password = hashed_password
        user.verification_token_hash = token_hash
        user.verification_token_expires = expires_at
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def mark_verified(self, user: User) -> User:
        user.is_verified = True
        user.verification_token_hash = None
        user.verification_token_expires = None
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def set_reset_token(self, user: User, token_hash: str, expires_at: datetime) -> User:
        user.reset_token_hash = token_hash
        user.reset_token_expires = expires_at
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def update_password(self, user: User, hashed_password: str) -> User:
        user.hashed_password = hashed_password
        user.reset_token_hash = None
        user.reset_token_expires = None
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def extend_subscription(self, user: User, *, days: int, traffic_limit_bytes: int | None = None) -> User:
        current_end = as_utc(user.subscription_end) if user.subscription_end else None
        base = current_end if current_end and current_end > utcnow() else utcnow()
        user.subscription_end = base + timedelta(days=days)
        if traffic_limit_bytes is not None:
            user.traffic_limit_bytes = traffic_limit_bytes
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def set_traffic_used(self, user: User, traffic_used: int) -> User:
        user.traffic_used = traffic_used
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def change_balance(self, user: User, amount_microrub: int) -> User:
        user.balance_microrub += amount_microrub
        user.updated_at = utcnow()
        await self.session.flush()
        return user

    async def list_users(self, *, limit: int = 100, offset: int = 0) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())
