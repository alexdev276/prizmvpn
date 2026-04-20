from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MICRORUB_IN_RUB = 1_000_000
DEVICE_MONTHLY_PRICE_RUB = Decimal("100")
DEVICE_MONTHLY_PRICE_MICRORUB = 100 * MICRORUB_IN_RUB
BILLING_MONTH_HOURS = 30 * 24
DEVICE_HOURLY_PRICE_MICRORUB = round(DEVICE_MONTHLY_PRICE_MICRORUB / BILLING_MONTH_HOURS)
MIN_RUB_TOPUP = Decimal("100")
MIN_USDT_TOPUP_RUB = Decimal("500")


def rub_to_microrub(amount: Decimal | int | str) -> int:
    normalized = Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return int(normalized * MICRORUB_IN_RUB)


def microrub_to_decimal(amount_microrub: int) -> Decimal:
    return (Decimal(amount_microrub) / MICRORUB_IN_RUB).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_rub_amount(value: str) -> Decimal:
    cleaned = value.replace("₽", "").replace("Р", "").replace("р", "").replace(",", ".").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Введите корректную сумму.") from exc
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_rub(amount_microrub: int, *, signed: bool = False) -> str:
    amount = microrub_to_decimal(amount_microrub)
    sign = ""
    if signed and amount_microrub > 0:
        sign = "+"
    if amount == amount.to_integral():
        return f"{sign}{int(amount)}₽"
    return f"{sign}{amount}₽"
