from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import get_current_user, get_payment_service
from app.models import User
from app.services.money import MIN_RUB_TOPUP, MIN_USDT_TOPUP_RUB, parse_rub_amount
from app.services.payments import PaymentError, PaymentService
from app.main_templates import templates

router = APIRouter(prefix="/payments")


@router.post("/yookassa/start")
async def start_yookassa(
    request: Request,
    plan_code: str = Form(...),
    user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        started = await payment_service.start_yookassa(user=user, plan_code=plan_code)
    except PaymentError as exc:
        return templates.TemplateResponse(request, "payment_error.html", {"error": str(exc)}, status_code=400)
    return RedirectResponse(started.confirmation_url, status_code=303)


@router.post("/cryptocloud/start")
async def start_cryptocloud(
    request: Request,
    plan_code: str = Form(...),
    user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        started = await payment_service.start_cryptocloud(user=user, plan_code=plan_code)
    except PaymentError as exc:
        return templates.TemplateResponse(request, "payment_error.html", {"error": str(exc)}, status_code=400)
    return RedirectResponse(started.confirmation_url, status_code=303)


@router.post("/yookassa/top-up")
async def top_up_yookassa(
    amount: str = Form(...),
    user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        amount_rub = parse_rub_amount(amount)
        if amount_rub < MIN_RUB_TOPUP:
            raise PaymentError(f"Минимальная сумма пополнения {int(MIN_RUB_TOPUP)}Р.")
        started = await payment_service.start_yookassa_topup(user=user, amount_rub=amount_rub)
    except (PaymentError, ValueError) as exc:
        return RedirectResponse(f"/dashboard/top-up?amount={quote(amount)}&error={quote(str(exc))}", status_code=303)
    return RedirectResponse(started.confirmation_url, status_code=303)


@router.post("/cryptocloud/top-up")
async def top_up_cryptocloud(
    amount: str = Form(...),
    user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        amount_rub = parse_rub_amount(amount)
        if amount_rub < MIN_USDT_TOPUP_RUB:
            raise PaymentError(f"Минимальная сумма пополнения {int(MIN_USDT_TOPUP_RUB)}Р.")
        started = await payment_service.start_cryptocloud_topup(user=user, amount_rub=amount_rub)
    except (PaymentError, ValueError) as exc:
        return RedirectResponse(f"/dashboard/top-up?amount={quote(amount)}&error={quote(str(exc))}", status_code=303)
    return RedirectResponse(started.confirmation_url, status_code=303)


@router.post("/webhooks/yookassa")
async def yookassa_webhook(
    payload: dict,
    x_webhook_secret: str | None = Header(default=None),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        payment = await payment_service.handle_yookassa_webhook(payload, webhook_secret=x_webhook_secret)
    except PaymentError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "payment_found": bool(payment)}


@router.post("/webhooks/cryptocloud")
async def cryptocloud_webhook(
    payload: dict,
    x_signature: str | None = Header(default=None),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        payment = await payment_service.handle_cryptocloud_webhook(payload, signature=x_signature)
    except PaymentError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "payment_found": bool(payment)}


@router.get("/test/success")
async def test_success(
    provider: str,
    id: str,
    payment_service: PaymentService = Depends(get_payment_service),
):
    await payment_service.mark_test_payment_paid(provider=provider, provider_payment_id=id)
    return RedirectResponse("/dashboard", status_code=303)
