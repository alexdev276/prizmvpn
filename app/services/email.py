from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib
import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    pass


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
        provider = self.settings.EMAIL_PROVIDER.strip().lower()
        if provider == "graph":
            await self._send_graph(email, subject, body)
            return
        if provider != "smtp":
            raise EmailError(f"Неизвестный провайдер отправки писем: {self.settings.EMAIL_PROVIDER}")
        await self._send_smtp(email, subject, body)

    async def _send_smtp(self, email: str, subject: str, body: str) -> None:
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

        try:
            await aiosmtplib.send(
                message,
                hostname=self.settings.SMTP_HOST,
                port=self.settings.SMTP_PORT,
                start_tls=self.settings.SMTP_STARTTLS,
                use_tls=self.settings.SMTP_SSL_TLS,
                validate_certs=True,
                **smtp_options,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            logger.exception("Failed to send email to %s via SMTP", email)
            raise EmailError("Не удалось отправить письмо. Проверьте SMTP-настройки.") from exc

    async def _send_graph(self, email: str, subject: str, body: str) -> None:
        access_token = await self._get_graph_access_token()
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": email,
                        }
                    }
                ],
            },
            "saveToSentItems": self.settings.MS_GRAPH_SAVE_TO_SENT_ITEMS,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.MS_GRAPH_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    "https://graph.microsoft.com/v1.0/me/sendMail",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.exception("Microsoft Graph sendMail failed: %s", exc.response.text[:1000])
            raise EmailError("Не удалось отправить письмо через Microsoft Graph.") from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.exception("Microsoft Graph sendMail request failed")
            raise EmailError("Не удалось отправить письмо через Microsoft Graph.") from exc

    async def _get_graph_access_token(self) -> str:
        if not self.settings.MS_GRAPH_CLIENT_ID or not self.settings.MS_GRAPH_REFRESH_TOKEN:
            raise EmailError("Microsoft Graph OAuth не настроен.")

        data = {
            "client_id": self.settings.MS_GRAPH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": self.settings.MS_GRAPH_REFRESH_TOKEN,
            "scope": "offline_access Mail.Send User.Read",
        }
        if self.settings.MS_GRAPH_CLIENT_SECRET:
            data["client_secret"] = self.settings.MS_GRAPH_CLIENT_SECRET

        token_url = f"https://login.microsoftonline.com/{self.settings.MS_GRAPH_TENANT}/oauth2/v2.0/token"
        try:
            async with httpx.AsyncClient(timeout=self.settings.MS_GRAPH_TIMEOUT_SECONDS) as client:
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                token_data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception("Microsoft Graph token refresh failed: %s", exc.response.text[:1000])
            raise EmailError("Не удалось обновить Microsoft Graph OAuth token.") from exc
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            logger.exception("Microsoft Graph token refresh request failed")
            raise EmailError("Не удалось обновить Microsoft Graph OAuth token.") from exc

        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise EmailError("Microsoft Graph OAuth не вернул access token.")
        return access_token
