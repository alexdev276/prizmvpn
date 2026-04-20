from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models import User
from app.repositories.users import UserRepository
from app.services.account import AccountService
from app.services.auth import AuthService
from app.services.email import EmailService
from app.services.payments import PaymentService
from app.services.remnawave import RemnawaveClient


def get_app_settings() -> Settings:
    return settings


def get_email_service(app_settings: Settings = Depends(get_app_settings)) -> EmailService:
    return EmailService(app_settings)


def get_remnawave_client(app_settings: Settings = Depends(get_app_settings)) -> RemnawaveClient:
    return RemnawaveClient(app_settings)


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    app_settings: Settings = Depends(get_app_settings),
    email_service: EmailService = Depends(get_email_service),
    remnawave_client: RemnawaveClient = Depends(get_remnawave_client),
) -> AuthService:
    return AuthService(session, app_settings, email_service, remnawave_client)


def get_payment_service(
    session: AsyncSession = Depends(get_session),
    app_settings: Settings = Depends(get_app_settings),
    remnawave_client: RemnawaveClient = Depends(get_remnawave_client),
) -> PaymentService:
    return PaymentService(session, app_settings, remnawave_client)


def get_account_service(
    session: AsyncSession = Depends(get_session),
    app_settings: Settings = Depends(get_app_settings),
) -> AccountService:
    return AccountService(session, app_settings)


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    app_settings: Settings = Depends(get_app_settings),
) -> User:
    token = request.cookies.get(app_settings.SESSION_COOKIE_NAME)
    subject = decode_access_token(token) if token else None
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход.")
    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Некорректная сессия.") from exc
    user = await UserRepository(session).get_by_id(user_id)
    if not user or not user.is_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется подтвержденный аккаунт.")
    return user


async def require_admin(
    user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_app_settings),
) -> User:
    if user.is_admin or user.email.lower() in app_settings.admin_email_set:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав.")
