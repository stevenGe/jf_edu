"""模板渲染辅助。"""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .security import make_csrf

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    ctx = dict(context or {})
    user = getattr(request.state, "user", None)
    ctx.setdefault("user", user)
    ctx["csrf"] = make_csrf(user.id) if user else ""
    return templates.TemplateResponse(
        request=request, name=name, context=ctx, status_code=status_code
    )
