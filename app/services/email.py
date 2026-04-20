from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib

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

        message = EmailMessage()
        message["From"] = formataddr((self.settings.SMTP_FROM_NAME, self.settings.SMTP_FROM))
        message["To"] = email
        message["Subject"] = subject
        message.set_content(body)

        smtp_options: dict[str, str] = {}
        if self.settings.SMTP_USERNAME and self.settings.SMTP_PASSWORD:
            smtp_options["username"] = self.settings.SMTP_USERNAME
            smtp_options["password"] = self.settings.SMTP_PASSWORD

        await aiosmtplib.send(
            message,
            hostname=self.settings.SMTP_HOST,
            port=self.settings.SMTP_PORT,
            start_tls=self.settings.SMTP_STARTTLS,
            use_tls=self.settings.SMTP_SSL_TLS,
            validate_certs=True,
            **smtp_options,
        )
