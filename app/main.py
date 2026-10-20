"""应用入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import NeedLogin
from .database import init_db
from .routers import auth_router, child, parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="积分小屋", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)
app.include_router(auth_router.router)
app.include_router(child.router)
app.include_router(parent.router)


@app.exception_handler(NeedLogin)
async def need_login_handler(_request, exc: NeedLogin):
    return RedirectResponse(exc.url, status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True}
