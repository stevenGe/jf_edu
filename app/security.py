"""密码哈希（stdlib pbkdf2，无外部依赖）+ 会话/CSRF 签名。"""
import hashlib
import hmac
import secrets

from itsdangerous import URLSafeTimedSerializer

from .config import SECRET_KEY_FILE

_PBKDF2_ITERS = 120_000


def hash_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), _PBKDF2_ITERS)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_secret(secret: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), _PBKDF2_ITERS)
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def _load_or_create_key() -> str:
    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text().strip()
    key = secrets.token_urlsafe(48)
    SECRET_KEY_FILE.write_text(key)
    try:
        SECRET_KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return key


_serializer: URLSafeTimedSerializer | None = None


def _ser() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(_load_or_create_key())
    return _serializer


def sign_session(user_id: int) -> str:
    return _ser().dumps({"uid": user_id}, salt="session")


def read_session(token: str) -> int | None:
    try:
        data = _ser().loads(token, salt="session", max_age=30 * 24 * 3600)
        return int(data["uid"])
    except Exception:
        return None


def make_csrf(user_id: int) -> str:
    return _ser().dumps({"uid": user_id}, salt="csrf")


def check_csrf(user_id: int, token: str) -> bool:
    try:
        data = _ser().loads(token, salt="csrf", max_age=6 * 3600)
        return int(data["uid"]) == user_id
    except Exception:
        return False
