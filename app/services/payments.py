from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Payment, User
from app.repositories.payments import PaymentRepository
from app.repositories.transactions import TransactionRepository
from app.repositories.users import UserRepository
from app.services.money import rub_to_microrub
from app.services.remnawave import RemnawaveClient


class PaymentError(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    amount_rub: Decimal
    amount_usd: Decimal
    days: int
    traffic_limit_bytes: int


PLANS: dict[str, Plan] = {
    "month": Plan("month", "30 дней", Decimal("199.00"), Decimal("3.00"), 30, 107374182400),
    "quarter": Plan("quarter", "90 дней", Decimal("499.00"), Decimal("7.00"), 90, 322122547200),
    "year": Plan("year", "365 дней", Decimal("1790.00"), Decimal("25.00"), 365, 1099511627776),
}


@dataclass(frozen=True)
class PaymentStart:
    payment: Payment
    confirmation_url: str


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        remnawave_client: RemnawaveClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.payments = PaymentRepository(session)
        self.users = UserRepository(session)
        self.transactions = TransactionRepository(session)
        self.remnawave_client = remnawave_client

    async def start_yookassa_topup(self, *, user: User, amount_rub: Decimal) -> PaymentStart:
        if self.settings.YOOKASSA_TEST_MODE or not self.settings.YOOKASSA_SHOP_ID:
            provider_payment_id = f"yk_topup_{secrets.token_urlsafe(12)}"
            payment = await self.payments.create(
                user_id=user.id,
                provider="yookassa",
                provider_payment_id=provider_payment_id,
                amount=amount_rub,
                currency="RUB",
                plan_code="balance",
                subscription_days=0,
                raw_payload={"test_mode": True, "topup": True},
            )
            await self.session.commit()
            return PaymentStart(payment, f"/payments/test/success?provider=yookassa&id={provider_payment_id}")

        payload = {
            "amount": {"value": str(amount_rub), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": f"{self.settings.BASE_URL}/dashboard"},
            "description": "Prizm VPN: пополнение баланса",
            "metadata": {"user_id": str(user.id), "plan_code": "balance"},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                auth=(self.settings.YOOKASSA_SHOP_ID, self.settings.YOOKASSA_SECRET_KEY),
                headers={"Idempotence-Key": secrets.token_urlsafe(24)},
            )
            response.raise_for_status()
        data = response.json()
        payment = await self.payments.create(
            user_id=user.id,
            provider="yookassa",
            provider_payment_id=data["id"],
            amount=amount_rub,
            currency="RUB",
            plan_code="balance",
            subscription_days=0,
            raw_payload=data,
        )
        await self.session.commit()
        return PaymentStart(payment, data["confirmation"]["confirmation_url"])

    async def start_cryptocloud_topup(self, *, user: User, amount_rub: Decimal) -> PaymentStart:
        if self.settings.CRYPTOCLOUD_TEST_MODE or not self.settings.CRYPTOCLOUD_API_KEY:
            provider_payment_id = f"cc_topup_{secrets.token_urlsafe(12)}"
            payment = await self.payments.create(
                user_id=user.id,
                provider="cryptocloud",
                provider_payment_id=provider_payment_id,
                amount=amount_rub,
                currency="RUB",
                plan_code="balance",
                subscription_days=0,
                raw_payload={"test_mode": True, "topup": True, "network": "USDT TRC20"},
            )
            await self.session.commit()
            return PaymentStart(payment, f"/payments/test/success?provider=cryptocloud&id={provider_payment_id}")

        payload = {
            "shop_id": self.settings.CRYPTOCLOUD_SHOP_ID,
            "amount": str(amount_rub),
            "currency": "USDT_TRC20",
            "order_id": f"{user.id}:balance:{secrets.token_hex(6)}",
            "email": user.email,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.cryptocloud.plus/v2/invoice/create",
                json=payload,
                headers={"Authorization": f"Token {self.settings.CRYPTOCLOUD_API_KEY}"},
            )
            response.raise_for_status()
        data = response.json()
        invoice = data.get("result") or data
        payment = await self.payments.create(
            user_id=user.id,
            provider="cryptocloud",
            provider_payment_id=str(invoice["uuid"]),
            amount=amount_rub,
            currency="RUB",
            plan_code="balance",
            subscription_days=0,
            raw_payload=data,
        )
        await self.session.commit()
        return PaymentStart(payment, invoice["link"])

    async def start_yookassa(self, *, user: User, plan_code: str) -> PaymentStart:
        plan = self._get_plan(plan_code)
        if self.settings.YOOKASSA_TEST_MODE or not self.settings.YOOKASSA_SHOP_ID:
            provider_payment_id = f"yk_test_{secrets.token_urlsafe(12)}"
            payment = await self.payments.create(
                user_id=user.id,
                provider="yookassa",
                provider_payment_id=provider_payment_id,
                amount=plan.amount_rub,
                currency="RUB",
                plan_code=plan.code,
                subscription_days=plan.days,
                raw_payload={"test_mode": True},
            )
            await self.session.commit()
            return PaymentStart(payment, f"/payments/test/success?provider=yookassa&id={provider_payment_id}")

        payload = {
            "amount": {"value": str(plan.amount_rub), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": f"{self.settings.BASE_URL}/dashboard"},
            "description": f"Prizm VPN: {plan.title}",
            "metadata": {"user_id": str(user.id), "plan_code": plan.code},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                auth=(self.settings.YOOKASSA_SHOP_ID, self.settings.YOOKASSA_SECRET_KEY),
                headers={"Idempotence-Key": secrets.token_urlsafe(24)},
            )
            response.raise_for_status()
        data = response.json()
        payment = await self.payments.create(
            user_id=user.id,
            provider="yookassa",
            provider_payment_id=data["id"],
            amount=plan.amount_rub,
            currency="RUB",
            plan_code=plan.code,
            subscription_days=plan.days,
            raw_payload=data,
        )
        await self.session.commit()
        return PaymentStart(payment, data["confirmation"]["confirmation_url"])

    async def start_cryptocloud(self, *, user: User, plan_code: str) -> PaymentStart:
        plan = self._get_plan(plan_code)
        if self.settings.CRYPTOCLOUD_TEST_MODE or not self.settings.CRYPTOCLOUD_API_KEY:
            provider_payment_id = f"cc_test_{secrets.token_urlsafe(12)}"
            payment = await self.payments.create(
                user_id=user.id,
                provider="cryptocloud",
                provider_payment_id=provider_payment_id,
                amount=plan.amount_usd,
                currency="USD",
                plan_code=plan.code,
                subscription_days=plan.days,
                raw_payload={"test_mode": True},
            )
            await self.session.commit()
            return PaymentStart(payment, f"/payments/test/success?provider=cryptocloud&id={provider_payment_id}")

        payload = {
            "shop_id": self.settings.CRYPTOCLOUD_SHOP_ID,
            "amount": str(plan.amount_usd),
            "currency": "USD",
            "order_id": f"{user.id}:{plan.code}:{secrets.token_hex(6)}",
            "email": user.email,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.cryptocloud.plus/v2/invoice/create",
                json=payload,
                headers={"Authorization": f"Token {self.settings.CRYPTOCLOUD_API_KEY}"},
            )
            response.raise_for_status()
        data = response.json()
        invoice = data.get("result") or data
        payment = await self.payments.create(
            user_id=user.id,
            provider="cryptocloud",
            provider_payment_id=str(invoice["uuid"]),
            amount=plan.amount_usd,
            currency="USD",
            plan_code=plan.code,
            subscription_days=plan.days,
            raw_payload=data,
        )
        await self.session.commit()
        return PaymentStart(payment, invoice["link"])

    async def handle_yookassa_webhook(self, payload: dict, webhook_secret: str | None = None) -> Payment | None:
        self._validate_optional_secret(self.settings.YOOKASSA_WEBHOOK_SECRET, webhook_secret)
        event = payload.get("event")
        payment_object = payload.get("object") or {}
        provider_payment_id = str(payment_object.get("id") or "")
        payment = await self.payments.get_by_provider_payment_id("yookassa", provider_payment_id)
        if not payment:
            return None
        if event == "payment.succeeded" and payment_object.get("status") == "succeeded":
            await self._activate_payment(payment, payload)
        elif event == "payment.canceled":
            await self.payments.mark_failed(payment, raw_payload=payload)
            await self.session.commit()
        return payment

    async def handle_cryptocloud_webhook(self, payload: dict, signature: str | None = None) -> Payment | None:
        self._validate_hmac_signature(payload, signature, self.settings.CRYPTOCLOUD_WEBHOOK_SECRET)
        provider_payment_id = str(payload.get("invoice_id") or payload.get("uuid") or payload.get("id") or "")
        payment = await self.payments.get_by_provider_payment_id("cryptocloud", provider_payment_id)
        if not payment:
            return None
        status = str(payload.get("status") or payload.get("invoice_status") or "").lower()
        if status in {"paid", "success", "succeeded"}:
            await self._activate_payment(payment, payload)
        elif status in {"canceled", "cancelled", "failed"}:
            await self.payments.mark_failed(payment, raw_payload=payload)
            await self.session.commit()
        return payment

    async def mark_test_payment_paid(self, *, provider: str, provider_payment_id: str) -> Payment:
        payment = await self.payments.get_by_provider_payment_id(provider, provider_payment_id)
        if not payment:
            raise PaymentError("Платеж не найден.")
        await self._activate_payment(payment, {"test_mode": True, "provider_payment_id": provider_payment_id})
        return payment

    def _get_plan(self, plan_code: str) -> Plan:
        plan = PLANS.get(plan_code)
        if not plan:
            raise PaymentError("Тариф не найден.")
        return plan

    async def _activate_payment(self, payment: Payment, payload: dict) -> None:
        if payment.status == "paid":
            return
        user = await self.users.get_by_id(payment.user_id)
        if not user:
            raise PaymentError("Пользователь платежа не найден.")
        if payment.plan_code == "balance":
            await self.payments.mark_paid(payment, raw_payload=payload)
            amount_microrub = rub_to_microrub(payment.amount)
            await self.users.change_balance(user, amount_microrub)
            await self.transactions.create(
                user_id=user.id,
                payment_id=payment.id,
                kind="topup",
                amount_microrub=amount_microrub,
                balance_after_microrub=user.balance_microrub,
                description="Пополнение баланса",
            )
            await self.session.commit()
            return
        plan = self._get_plan(payment.plan_code)
        await self.payments.mark_paid(payment, raw_payload=payload)
        await self.users.extend_subscription(user, days=payment.subscription_days, traffic_limit_bytes=plan.traffic_limit_bytes)
        if user.remnawave_uuid:
            await self.remnawave_client.extend_user(
                remnawave_uuid=user.remnawave_uuid,
                days=payment.subscription_days,
                traffic_limit_bytes=plan.traffic_limit_bytes,
            )
        await self.session.commit()

    @staticmethod
    def _validate_optional_secret(expected: str, supplied: str | None) -> None:
        if expected and not hmac.compare_digest(expected, supplied or ""):
            raise PaymentError("Неверная подпись вебхука.")

    @staticmethod
    def _validate_hmac_signature(payload: dict, signature: str | None, secret: str) -> None:
        if not secret:
            return
        canonical = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise PaymentError("Неверная подпись вебхука.")
