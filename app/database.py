"""数据库引擎与会话。"""
from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import DB_PATH


def _make_engine():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    e = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

    @event.listens_for(e, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return e


engine = _make_engine()


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：请求级会话。"""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    import app.models  # noqa: F401  确保表模型已注册

    SQLModel.metadata.create_all(engine)
