from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.repositories.payments import PaymentRepository
from app.repositories.users import UserRepository
from app.main_templates import templates

router = APIRouter(prefix="/admin")


@router.get("")
async def admin_index(
    request: Request,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    users = await UserRepository(session).list_users()
    payments = await PaymentRepository(session).list_all(limit=20)
    return templates.TemplateResponse(request, "admin/index.html", {"users": users, "payments": payments})


@router.post("/users/{user_id}/verify")
async def manual_verify_user(
    user_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    if not user.is_verified:
        await repo.mark_verified(user)
    await session.commit()
    return RedirectResponse("/admin", status_code=303)
