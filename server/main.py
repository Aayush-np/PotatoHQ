"""PotatoHQ application assembly."""
import asyncio
import json
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from . import db, hub, security, wsapi
from .config import SESSION_COOKIE, WEB_DIR
from .routes import auth, music, rooms, social

import os

app = FastAPI(title="PotatoHQ", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
async def startup() -> None:
    db.init()


# --- CSRF: mutating API calls must carry our custom header (cross-site forms/JS can't) ---

@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.url.path.startswith("/api"):
        if request.headers.get("x-potato") != "1":
            return _json_403("Blocked: missing PotatoHQ request header.")
    return await call_next(request)


def _json_403(message: str):
    from starlette.responses import JSONResponse
    return JSONResponse({"detail": message}, status_code=403)


# --- REST routers ---

app.include_router(auth.router, prefix="/api")
app.include_router(social.router, prefix="/api")
app.include_router(rooms.router, prefix="/api")
app.include_router(music.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"ok": True, "potatoes": "warm", "serverTime": time.time()}


# --- WebSocket ---

async def _origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser clients (tests) are fine; auth still required
    host = ws.headers.get("host", "")
    return origin in (f"http://{host}", f"https://{host}", "http://localhost:8420", "http://127.0.0.1:8420")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not await _origin_ok(ws):
        await ws.close(code=4403)
        return
    user = security.user_from_token(ws.cookies.get(SESSION_COOKIE))
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = hub.Conn(ws, user)
    await hub.connect(conn)

    window_start = time.time()
    received = 0
    try:
        while True:
            raw = await ws.receive_text()
            received += 1
            if received > 250:
                if time.time() - window_start > 5:
                    window_start = time.time()
                    received = 1
                else:
                    await ws.close(code=4409)
                    break
            if len(raw) > 65536:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if len(str(data.get("type", ""))) > 32:
                continue
            if os.getenv("POTATO_WS_DEBUG"):
                print(f"[ws-debug] user={conn.user_id} type={data.get('type')} ", flush=True)
            await wsapi.dispatch(conn, data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.disconnect(conn)


# --- static frontend ---

app.mount("/uploads", StaticFiles(directory=str((WEB_DIR.parent / "data" / "uploads"))), name="uploads")
app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
