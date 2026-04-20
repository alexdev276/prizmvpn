from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import utcnow
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    verification_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    verification_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    remnawave_uuid: Mapped[str | None] = mapped_column(String(128), index=True)
    subscription_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    traffic_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    balance_microrub: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    payments: Mapped[list["Payment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["AccountTransaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_provider_provider_id", "provider", "provider_payment_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="RUB", nullable=False)
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False)
    subscription_days: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="payments")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    config_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    remnawave_uuid: Mapped[str | None] = mapped_column(String(128), index=True)
    remnawave_username: Mapped[str | None] = mapped_column(String(320), index=True)
    remnawave_subscription_url: Mapped[str | None] = mapped_column(Text)
    remnawave_raw: Mapped[dict | None] = mapped_column(JSON)
    traffic_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_billed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="devices")
    transactions: Mapped[list["AccountTransaction"]] = relationship(back_populates="device")


class AccountTransaction(Base):
    __tablename__ = "account_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_microrub: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_microrub: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="transactions")
    device: Mapped[Device | None] = relationship(back_populates="transactions")
