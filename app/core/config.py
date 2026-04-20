from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Prizm VPN"
    APP_ENV: str = "local"
    DEBUG: bool = False
    BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/prizm_vpn"
    DB_ECHO: bool = False

    SECRET_KEY: str = Field(default="change-me-in-.env")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 14
    SESSION_COOKIE_NAME: str = "prizm_session"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@example.com"
    SMTP_FROM_NAME: str = "Prizm VPN"
    SMTP_STARTTLS: bool = True
    SMTP_SSL_TLS: bool = False

    REMNA_BASE_URL: str = "http://localhost:3000"
    REMNA_TOKEN: str = ""
    REMNA_TIMEOUT_SECONDS: float = 10.0
    REMNA_RETRIES: int = 2
    REMNA_MOCK_MODE: bool = True
    REMNA_DEFAULT_DAYS: int = 30
    REMNA_TRAFFIC_LIMIT_BYTES: int = 107374182400
    REMNA_SUBSCRIPTION_PATH_TEMPLATE: str = "/api/sub/{uuid}"

    ADMIN_EMAILS: str = ""

    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_WEBHOOK_SECRET: str = ""
    YOOKASSA_TEST_MODE: bool = True

    CRYPTOCLOUD_API_KEY: str = ""
    CRYPTOCLOUD_SHOP_ID: str = ""
    CRYPTOCLOUD_WEBHOOK_SECRET: str = ""
    CRYPTOCLOUD_TEST_MODE: bool = True

    LOGIN_RATE_LIMIT: int = 8
    LOGIN_RATE_WINDOW_SECONDS: int = 60 * 10
    RESET_RATE_LIMIT: int = 3
    RESET_RATE_WINDOW_SECONDS: int = 60 * 15

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.ADMIN_EMAILS.split(",") if email.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

