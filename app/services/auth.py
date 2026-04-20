from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    as_utc,
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    utcnow,
    verify_password,
)
from app.models import User
from app.repositories.users import UserRepository
from app.services.email import EmailError, EmailService


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class RegistrationResult:
    email: str


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        email_service: EmailService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.email_service = email_service

    async def register(self, *, email: str, password: str) -> RegistrationResult:
        email = email.strip().lower()
        existing = await self.users.get_by_email(email)
        password_hash = hash_password(password)

        if existing:
            raise AuthError("Пользователь с таким email уже зарегистрирован.")

        await self.users.create(
            email=email,
            hashed_password=password_hash,
            verification_token_hash=None,
            verification_token_expires=None,
            is_verified=True,
            is_admin=email in self.settings.admin_email_set,
        )

        await self.session.commit()
        return RegistrationResult(email=email)

    async def confirm_email(self, token: str) -> User:
        user = await self.users.get_by_verification_token_hash(hash_token(token))
        if not user or not user.verification_token_expires or as_utc(user.verification_token_expires) < utcnow():
            raise AuthError("Ссылка подтверждения недействительна или устарела.")

        await self.users.mark_verified(user)
        await self.session.commit()
        return user

    async def login(self, *, email: str, password: str) -> str:
        user = await self.users.get_by_email(email.strip().lower())
        if not user or not verify_password(password, user.hashed_password):
            raise AuthError("Неверный email или пароль.")
        return create_access_token(str(user.id))

    async def request_password_reset(self, *, email: str) -> None:
        user = await self.users.get_by_email(email.strip().lower())
        if not user:
            return

        token = generate_token()
        await self.users.set_reset_token(user, hash_token(token), utcnow() + timedelta(hours=24))
        await self.session.commit()
        try:
            await self.email_service.send_password_reset_email(user.email, token)
        except EmailError as exc:
            raise AuthError(str(exc)) from exc

    async def reset_password(self, *, token: str, new_password: str) -> None:
        user = await self.users.get_by_reset_token_hash(hash_token(token))
        if not user or not user.reset_token_expires or as_utc(user.reset_token_expires) < utcnow():
            raise AuthError("Ссылка сброса пароля недействительна или устарела.")
        await self.users.update_password(user, hash_password(new_password))
        await self.session.commit()
