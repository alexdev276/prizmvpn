from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.api.deps import get_app_settings, get_auth_service
from app.core.config import Settings
from app.core.rate_limit import rate_limiter
from app.services.auth import AuthError, AuthService
from app.main_templates import templates

router = APIRouter()


@router.get("/register")
async def register_form(request: Request):
    return templates.TemplateResponse(request, "auth/register.html")


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
):
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Пароль должен быть не короче 8 символов.", "email": email},
            status_code=400,
        )
    try:
        await auth_service.register(email=email, password=password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": str(exc), "email": email},
            status_code=400,
        )
    return RedirectResponse(f"/check-email?email={email}", status_code=303)


@router.get("/check-email")
async def check_email(request: Request, email: str = ""):
    return templates.TemplateResponse(request, "auth/check_email.html", {"email": email})


@router.get("/verify-email")
async def verify_email(request: Request, token: str, auth_service: AuthService = Depends(get_auth_service)):
    try:
        await auth_service.confirm_email(token)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/verify_result.html",
            {"ok": False, "message": str(exc)},
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "auth/verify_result.html",
        {"ok": True, "message": "Email подтвержден. Аккаунт активирован."},
    )


@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
    app_settings: Settings = Depends(get_app_settings),
):
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login:{client_ip}:{email.lower()}", app_settings.LOGIN_RATE_LIMIT, app_settings.LOGIN_RATE_WINDOW_SECONDS)
    try:
        token = await auth_service.login(email=email, password=password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": str(exc), "email": email},
            status_code=400,
        )
    response = RedirectResponse("/account", status_code=303)
    response.set_cookie(
        app_settings.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=app_settings.APP_ENV == "production",
        samesite="lax",
        max_age=app_settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


@router.post("/logout")
async def logout(app_settings: Settings = Depends(get_app_settings)):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(app_settings.SESSION_COOKIE_NAME)
    return response


@router.get("/forgot-password")
async def forgot_password_form(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html")


@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    email: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
    app_settings: Settings = Depends(get_app_settings),
):
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"reset:{client_ip}:{email.lower()}", app_settings.RESET_RATE_LIMIT, app_settings.RESET_RATE_WINDOW_SECONDS)
    await auth_service.request_password_reset(email=email)
    return templates.TemplateResponse(
        request,
        "auth/forgot_password.html",
        {"sent": True, "email": email},
    )


@router.get("/reset-password")
async def reset_password_form(request: Request, token: str):
    return templates.TemplateResponse(request, "auth/reset_password.html", {"token": token})


@router.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
):
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": "Пароль должен быть не короче 8 символов."},
            status_code=400,
        )
    try:
        await auth_service.reset_password(token=token, new_password=password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": str(exc)},
            status_code=400,
        )
    return templates.TemplateResponse(request, "auth/reset_done.html")
