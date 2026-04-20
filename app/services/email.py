from __future__ import annotations

import logging

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_verification_email(self, email: str, token: str) -> None:
        link = f"{self.settings.BASE_URL}/verify-email?token={token}"
        subject = "Подтвердите email для Prizm VPN"
        body = (
            "Здравствуйте!\n\n"
            "Чтобы активировать аккаунт Prizm VPN, перейдите по ссылке:\n"
            f"{link}\n\n"
            "Ссылка действует 24 часа."
        )
        await self._send(email, subject, body)

    async def send_password_reset_email(self, email: str, token: str) -> None:
        link = f"{self.settings.BASE_URL}/reset-password?token={token}"
        subject = "Сброс пароля Prizm VPN"
        body = (
            "Здравствуйте!\n\n"
            "Чтобы задать новый пароль, перейдите по ссылке:\n"
            f"{link}\n\n"
            "Ссылка действует 24 часа. Если вы не запрашивали сброс пароля, просто проигнорируйте письмо."
        )
        await self._send(email, subject, body)

    async def _send(self, email: str, subject: str, body: str) -> None:
        if not self.settings.SMTP_HOST:
            logger.info("SMTP is not configured. Email to %s: %s\n%s", email, subject, body)
            return

        from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

        config = ConnectionConfig(
            MAIL_USERNAME=self.settings.SMTP_USERNAME,
            MAIL_PASSWORD=self.settings.SMTP_PASSWORD,
            MAIL_FROM=self.settings.SMTP_FROM,
            MAIL_FROM_NAME=self.settings.SMTP_FROM_NAME,
            MAIL_PORT=self.settings.SMTP_PORT,
            MAIL_SERVER=self.settings.SMTP_HOST,
            MAIL_STARTTLS=self.settings.SMTP_STARTTLS,
            MAIL_SSL_TLS=self.settings.SMTP_SSL_TLS,
            USE_CREDENTIALS=bool(self.settings.SMTP_USERNAME and self.settings.SMTP_PASSWORD),
            VALIDATE_CERTS=True,
        )
        message = MessageSchema(
            subject=subject,
            recipients=[email],
            body=body,
            subtype=MessageType.plain,
        )
        await FastMail(config).send_message(message)

