"""认证与访问控制。"""
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from sqlmodel import Session

from .config import SESSION_COOKIE
from .database import engine
from .models import User
from .security import check_csrf, read_session


class NeedLogin(Exception):
    """未登录/角色不符 → 由全局异常处理器重定向。"""

    def __init__(self, url: str = "/login"):
        self.url = url
        super().__init__(url)


def get_current_user(request: Request) -> User | None:
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = read_session(token)
    if uid is None:
        return None
    with Session(engine) as s:
        user = s.get(User, uid)
    if user is None or not user.active:
        return None
    request.state.user = user
    return user


def _require_role(request: Request, role: str) -> User:
    user = get_current_user(request)
    if user is None:
        raise NeedLogin("/login")
    if user.role != role:
        raise NeedLogin("/parent" if user.role == "parent" else "/")
    return user


def require_child(request: Request) -> User:
    return _require_role(request, "child")


def require_parent(request: Request) -> User:
    return _require_role(request, "parent")


async def csrf_protect(request: Request) -> None:
    """所有 POST 表单统一校验 CSRF token（依赖注入使用）。"""
    if request.method != "POST":
        return
    user = get_current_user(request)
    form = await request.form()
    token = str(form.get("_csrf") or "")
    if user is None or not check_csrf(user.id, token):
        raise HTTPException(status_code=400, detail="页面已过期，请返回刷新后重试")


# ---- 登录限流（内存级，单进程家庭规模够用） ----
_FAIL_WINDOW = 600  # 秒
_FAIL_MAX = 8
_fails: dict[str, list[float]] = defaultdict(list)


def login_blocked(ip: str) -> bool:
    now = time.monotonic()
    alive = [t for t in _fails.get(ip, []) if now - t < _FAIL_WINDOW]
    _fails[ip] = alive
    return len(alive) >= _FAIL_MAX


def record_login_fail(ip: str) -> None:
    _fails[ip].append(time.monotonic())


def clear_login_fails(ip: str) -> None:
    _fails.pop(ip, None)
