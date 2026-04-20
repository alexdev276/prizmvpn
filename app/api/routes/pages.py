from fastapi import APIRouter, Request

from app.main_templates import templates

router = APIRouter()


@router.get("/")
async def landing(request: Request):
    screens = [f"landing/iPhone 16 - {index}.svg" for index in range(1, 9)]
    return templates.TemplateResponse(request, "index.html", {"screens": screens})


@router.get("/instructions/{platform}")
async def instruction_placeholder(request: Request, platform: str):
    return templates.TemplateResponse(request, "instruction.html", {"platform": platform})
