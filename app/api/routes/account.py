from __future__ import annotations

from datetime import datetime

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_account_service, get_current_user
from app.core.security import as_utc, utcnow
from app.db.session import get_session
from app.models import User
from app.repositories.transactions import TransactionRepository
from app.services.account import AccountError, AccountService, device_monthly_price_label
from app.services.money import MIN_RUB_TOPUP, MIN_USDT_TOPUP_RUB, format_rub
from app.services.remnawave import RemnawaveError
from app.main_templates import templates

router = APIRouter()


def format_bytes(value: int | None) -> str:
    value = value or 0
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "Б" else f"{int(size)} {unit}"
        size /= 1024
    return f"{value} Б"


def subscription_status(subscription_end: datetime | None) -> str:
    if not subscription_end:
        return "Не активна"
    return "Активна" if as_utc(subscription_end) > utcnow() else "Истекла"


@router.get("/account")
async def account(
    request: Request,
    modal: str | None = None,
    device_id: int | None = None,
    error: str | None = None,
    user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
):
    await account_service.bill_user_devices(user)
    await account_service.refresh_device_usage(user)

    device_views = await account_service.list_device_views(user)
    selected_device = next((view for view in device_views if view.device.id == device_id), None)
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "devices": device_views,
            "modal": modal,
            "selected_device": selected_device,
            "error": error,
            "status": subscription_status(user.subscription_end),
            "balance": format_rub(user.balance_microrub),
            "device_price": device_monthly_price_label(),
            "traffic_used": format_bytes(user.traffic_used),
            "traffic_limit": format_bytes(user.traffic_limit_bytes),
        },
    )


@router.get("/account/config")
async def download_config(
    _user: User = Depends(get_current_user),
):
    raise HTTPException(status_code=410, detail="Конфигурации теперь привязаны к устройствам.")


@router.get("/account/top-up")
async def top_up_page(
    request: Request,
    amount: str = "150",
    error: str | None = None,
    user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
):
    await account_service.bill_user_devices(user)
    return templates.TemplateResponse(
        request,
        "top_up.html",
        {
            "user": user,
            "amount": amount,
            "error": error,
            "balance": format_rub(user.balance_microrub),
            "min_rub": int(MIN_RUB_TOPUP),
            "min_usdt": int(MIN_USDT_TOPUP_RUB),
        },
    )


@router.get("/account/history")
async def history_page(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    account_service: AccountService = Depends(get_account_service),
):
    await account_service.bill_user_devices(user)
    transactions = await TransactionRepository(session).list_for_user(user.id)
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "user": user,
            "balance": format_rub(user.balance_microrub),
            "transactions": transactions,
            "format_rub": format_rub,
        },
    )


@router.post("/account/devices")
async def add_device(
    title: str = Form("IPhone 16"),
    user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
):
    try:
        device = await account_service.add_device(user, title=title)
    except AccountError as exc:
        return RedirectResponse(f"/account?modal=add&error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/account?device_id={device.id}", status_code=303)


@router.post("/account/devices/{device_id}/replace")
async def replace_device(
    device_id: int,
    user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
):
    try:
        device = await account_service.replace_device_config(user, device_id)
    except AccountError as exc:
        return RedirectResponse(f"/account?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/account?device_id={device.id}", status_code=303)


@router.post("/account/devices/{device_id}/delete")
async def delete_device(
    device_id: int,
    user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
):
    try:
        await account_service.delete_device(user, device_id)
    except AccountError as exc:
        return RedirectResponse(f"/account?error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/account", status_code=303)


@router.get("/subscription/{public_id}/{config_uuid}.txt")
async def public_device_config(
    public_id: str,
    config_uuid: str,
    account_service: AccountService = Depends(get_account_service),
):
    device = await account_service.get_public_device(public_id, config_uuid)
    if not device:
        raise HTTPException(status_code=404, detail="Конфигурация не найдена.")
    try:
        config = await account_service.render_device_config(device)
    except AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemnawaveError as exc:
        raise HTTPException(status_code=502, detail="Remnawave временно недоступен.") from exc
    return PlainTextResponse(config, media_type="text/plain; charset=utf-8")
