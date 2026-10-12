"""Password hashing (stdlib scrypt), session tokens, input validation."""
import hashlib
import hmac
import re
import secrets
import time

from . import db
from .config import SESSION_TTL

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=64
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=64,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.run(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        _token_hash(token), user_id, now, now + SESSION_TTL,
    )
    # opportunistic purge of long-expired sessions
    if secrets.randbelow(50) == 0:
        db.run("DELETE FROM sessions WHERE expires_at < ?", now - 60 * 60 * 24 * 7)
    return token


def user_from_token(token: str | None):
    if not token:
        return None
    row = db.one(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        _token_hash(token), time.time(),
    )
    return row


def destroy_session(token: str | None) -> None:
    if token:
        db.run("DELETE FROM sessions WHERE token_hash = ?", _token_hash(token))


def valid_username(name: str) -> bool:
    return bool(USERNAME_RE.fullmatch(name or ""))


def valid_email(email: str) -> bool:
    return len(email or "") <= 254 and bool(EMAIL_RE.fullmatch(email or ""))


def valid_password(pw: str) -> bool:
    return isinstance(pw, str) and 8 <= len(pw) <= 128
