"""Music discovery endpoints (YouTube Music metadata via ytmusicapi)."""
from fastapi import APIRouter, Depends, HTTPException

from .. import db, player, ytm
from ..ratelimit import check
from .auth import require_user

router = APIRouter()


def _music_fail(e: Exception):
    raise HTTPException(
        503, "The spud couldn't reach YouTube Music. Check the connection and try again."
    )


@router.get("/music/search")
async def music_search(
    q: str = "", filter: str = "songs", limit: int = 20,
    user: dict = Depends(require_user),
):
    q = (q or "").strip()
    if not q or len(q) > 150:
        raise HTTPException(400, "Type something to search for.")
    if filter not in ("songs", "artists", "albums", "playlists"):
        filter = "songs"
    limit = max(1, min(limit, 30))
    if not check(f"msearch:{user['id']}", 30, 60):
        raise HTTPException(429, "The spud needs a moment. Try again shortly.")
    try:
        return await ytm.search(q, filter, limit)
    except ytm.MusicUnavailable as e:
        _music_fail(e)


@router.get("/music/related/{video_id}")
async def music_related(video_id: str, user: dict = Depends(require_user)):
    if not ytm.VIDEO_ID_RE.fullmatch(video_id):
        raise HTTPException(400, "Bad video ID.")
    if not check(f"msearch:{user['id']}", 30, 60):
        raise HTTPException(429, "The spud needs a moment. Try again shortly.")
    try:
        return {"type": "songs", "results": await ytm.related_tracks(video_id, limit=20)}
    except ytm.MusicUnavailable as e:
        _music_fail(e)


@router.get("/music/album/{browse_id}")
async def music_album(browse_id: str, user: dict = Depends(require_user)):
    if not check(f"msearch:{user['id']}", 30, 60):
        raise HTTPException(429, "The spud needs a moment. Try again shortly.")
    try:
        return await ytm.album_tracks(browse_id)
    except ytm.MusicUnavailable as e:
        _music_fail(e)


@router.get("/music/playlist/{playlist_id}")
async def music_playlist(playlist_id: str, user: dict = Depends(require_user)):
    if not check(f"msearch:{user['id']}", 30, 60):
        raise HTTPException(429, "The spud needs a moment. Try again shortly.")
    try:
        return await ytm.playlist_tracks(playlist_id)
    except ytm.MusicUnavailable as e:
        _music_fail(e)


@router.get("/music/artist/{browse_id}")
async def music_artist(browse_id: str, user: dict = Depends(require_user)):
    if not check(f"msearch:{user['id']}", 30, 60):
        raise HTTPException(429, "The spud needs a moment. Try again shortly.")
    try:
        return await ytm.artist_tracks(browse_id)
    except ytm.MusicUnavailable as e:
        _music_fail(e)


@router.get("/music/state/{room_id}")
async def music_state(room_id: int, user: dict = Depends(require_user)):
    member = db.one(
        "SELECT 1 FROM members WHERE room_id = ? AND user_id = ? AND status = 'active'",
        room_id, user["id"],
    )
    if not member:
        raise HTTPException(403, "This is a private room — you need an invite.")
    await player.reconcile(room_id)
    return player.snapshot(room_id)
