"""登录 / 登出。"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..auth import (
    clear_login_fails,
    get_current_user,
    login_blocked,
    record_login_fail,
)
from ..config import SESSION_COOKIE, SESSION_MAX_AGE
from ..database import get_session
from ..models import User
from ..security import sign_session, verify_secret
from ..templating import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    get_current_user(request)  # 填充 request.state，供 render 使用
    user = getattr(request.state, "user", None)
    if user is not None:
        return RedirectResponse("/parent" if user.role == "parent" else "/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    role: str = Form(...),
    pin: str = Form(""),
    name: str = Form(""),
    password: str = Form(""),
    db: DBSession = Depends(get_session),
):
    ip = request.client.host if request.client else "?"
    get_current_user(request)
    if login_blocked(ip):
        return render(
            request, "login.html", {"error": "尝试次数太多，请 10 分钟后再试"}, status_code=429
        )

    user: User | None = None
    if role == "child":
        pin = pin.strip()
        if pin.isdigit() and len(pin) == 4:
            child = db.exec(
                select(User).where(User.role == "child", User.active == True)  # noqa: E712
            ).first()
            if child is not None and verify_secret(pin, child.secret_hash):
                user = child
    elif role == "parent":
        name = name.strip()
        candidate = db.exec(
            select(User).where(User.role == "parent", User.name == name)
        ).first()
        if candidate is not None and candidate.active and verify_secret(password, candidate.secret_hash):
            user = candidate

    if user is None:
        record_login_fail(ip)
        return render(request, "login.html", {"error": "密码不对，再试一次"}, status_code=401)

    clear_login_fails(ip)
    resp = RedirectResponse("/parent" if user.role == "parent" else "/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        sign_session(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
