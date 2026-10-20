"""全局配置。数据库统一存上海本地时间（naive datetime）。"""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("JF_EDU_DB") or DATA_DIR / "jf_edu.db")
SECRET_KEY_FILE = Path(os.environ.get("JF_SECRET_FILE") or DATA_DIR / "secret.key")

TZ = ZoneInfo("Asia/Shanghai")
APP_NAME = "积分小屋"
SESSION_COOKIE = "jf_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 天


def now_local() -> datetime:
    """当前上海本地时间（naive，数据库统一存这个，避免服务器时区干扰）。"""
    return datetime.now(TZ).replace(tzinfo=None)
