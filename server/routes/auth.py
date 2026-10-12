"""Authentication and profile endpoints."""
import secrets
import time

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, Response, UploadFile

from .. import db, hub, models, security
from ..config import (
    AVATARS_DIR, COOKIE_SECURE, MAX_DISPLAY_LEN, MAX_UPLOAD_BYTES,
    SESSION_COOKIE, SESSION_TTL, STUN_SERVERS, TURN_CRED, TURN_URL, TURN_USER,
)
from ..ratelimit import check

router = APIRouter()


def require_user(request: Request) -> dict:
    user = security.user_from_token(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(401, "You need to sign in first.")
    return user


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_TTL, httponly=True, samesite="lax", path="/", secure=COOKIE_SECURE,
    )


def _public_user(u: dict) -> dict:
    return models.user_card(u, online=hub.is_online(u["id"]), activity=hub.activity_of(u["id"]))


@router.post("/auth/register")
async def register(request: Request, response: Response, payload: dict = Body(...)):
    if not check(f"reg:{client_key(request)}", 20, 600):
        raise HTTPException(429, "Slow down, spud. Try again in a few minutes.")
    email = str(payload.get("email") or "").strip().lower()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    display_name = str(payload.get("displayName") or "").strip() or username

    if not security.valid_email(email):
        raise HTTPException(400, "That email doesn't look right.")
    if not security.valid_username(username):
        raise HTTPException(400, "Usernames are 3-24 letters, numbers, dots, dashes or underscores.")
    if not security.valid_password(password):
        raise HTTPException(400, "Passwords need at least 8 characters.")
    if len(display_name) > MAX_DISPLAY_LEN:
        raise HTTPException(400, "Display name is too long.")
    if db.one("SELECT 1 FROM users WHERE email = ?", email):
        raise HTTPException(409, "That email is already in the HQ.")
    if db.one("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPException(409, "Username taken. Another spud got there first.")

    uid = db.insert(
        """INSERT INTO users (email, username, password_hash, display_name, created_at, last_seen)
           VALUES (?,?,?,?,?,?)""",
        email, username, security.hash_password(password), display_name, time.time(), time.time(),
    )
    token = security.create_session(uid)
    _set_session_cookie(response, token)
    user = db.one("SELECT * FROM users WHERE id = ?", uid)
    return {"user": _public_user(user)}


@router.post("/auth/login")
async def login(request: Request, response: Response, payload: dict = Body(...)):
    if not check(f"login:{client_key(request)}", 12, 300):
        raise HTTPException(429, "Too many attempts. Give it a minute.")
    ident = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    user = db.one("SELECT * FROM users WHERE email = ? OR username = ?", ident, ident)
    if not user or not security.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password.")
    db.run("UPDATE users SET last_seen = ? WHERE id = ?", time.time(), user["id"])
    token = security.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"user": _public_user(user)}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    security.destroy_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {"user": _public_user(user)}


@router.patch("/me")
async def update_me(
    request: Request, payload: dict = Body(...), user: dict = Depends(require_user),
):
    display_name = payload.get("displayName")
    if display_name is not None:
        display_name = str(display_name).strip()
        if not display_name or len(display_name) > MAX_DISPLAY_LEN:
            raise HTTPException(400, "Display name must be 1-40 characters.")
        db.run("UPDATE users SET display_name = ? WHERE id = ?", display_name, user["id"])

    username = payload.get("username")
    if username:
        username = str(username).strip()
        if not security.valid_username(username):
            raise HTTPException(400, "Usernames are 3-24 letters, numbers, dots, dashes or underscores.")
        if username.lower() != user["username"].lower() and db.one(
            "SELECT 1 FROM users WHERE username = ?", username
        ):
            raise HTTPException(409, "Username taken. Another spud got there first.")
        db.run("UPDATE users SET username = ? WHERE id = ?", username, user["id"])

    current = payload.get("currentPassword")
    new = payload.get("newPassword")
    if new is not None:
        if not current or not security.verify_password(str(current), user["password_hash"]):
            raise HTTPException(403, "Current password is wrong.")
        if not security.valid_password(str(new)):
            raise HTTPException(400, "New passwords need at least 8 characters.")
        db.run(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            security.hash_password(str(new)), user["id"],
        )

    fresh = db.one("SELECT * FROM users WHERE id = ?", user["id"])
    return {"user": _public_user(fresh)}


ALLOWED_UPLOAD_MAGIC = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}


@router.post("/me/avatar")
async def upload_avatar(
    request: Request, file: UploadFile = File(...), user: dict = Depends(require_user),
):
    if not check(f"avatar:{user['id']}", 10, 300):
        raise HTTPException(429, "Easy on the uploads, spud.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large — keep it under 2 MB.")
    ext = None
    for magic, e in ALLOWED_UPLOAD_MAGIC.items():
        if raw.startswith(magic):
            ext = e
            break
    if ext is None and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ext = ".webp"
    if ext is None:
        raise HTTPException(400, "Only PNG, JPEG or WebP images, please.")

    name = f"u{user['id']}_{secrets.token_hex(6)}{ext}"
    path = AVATARS_DIR / name
    path.write_bytes(raw)
    rel = f"avatars/{name}"
    # clean up previous uploads
    old = user.get("avatar_path")
    if old:
        try:
            (AVATARS_DIR / old.split("/")[-1]).unlink(missing_ok=True)
        except Exception:
            pass
    db.run("UPDATE users SET avatar_path = ? WHERE id = ?", rel, user["id"])
    fresh = db.one("SELECT * FROM users WHERE id = ?", user["id"])
    await hub.broadcast_presence(user["id"])
    return {"user": _public_user(fresh)}


@router.get("/rtc/config")
async def rtc_config(user: dict = Depends(require_user)):
    """WebRTC ICE servers for voice. STUN always; TURN if configured."""
    servers = [{"urls": STUN_SERVERS}]
    if TURN_URL:
        entry = {"urls": [TURN_URL]}
        if TURN_USER:
            entry["username"] = TURN_USER
            entry["credential"] = TURN_CRED
        servers.append(entry)
    return {"iceServers": servers}


@router.get("/users/{uid}")
async def get_user(uid: int, user: dict = Depends(require_user)):
    target = db.one("SELECT * FROM users WHERE id = ?", uid)
    if not target:
        raise HTTPException(404, "No such spud.")
    card = _public_user(target)
    card["lastSeen"] = target["last_seen"]
    return {"user": card}


@router.get("/users/{uid}/avatar")
async def get_avatar(uid: int):
    u = db.one("SELECT * FROM users WHERE id = ?", uid)
    if u and u.get("avatar_path"):
        from fastapi.responses import FileResponse
        path = AVATARS_DIR / u["avatar_path"].split("/")[-1]
        if path.exists():
            return FileResponse(
                path, headers={"Cache-Control": "private, max-age=86400"}
            )
    from fastapi import Response as FResponse
    return FResponse(
        content=models.potato_avatar_svg(uid),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=86400"},
    )
