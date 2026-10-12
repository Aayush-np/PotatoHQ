"""Friendships and the bootstrap payload."""
import time

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db, hub, models
from ..ratelimit import check
from .auth import require_user

router = APIRouter()


@router.get("/bootstrap")
async def bootstrap(user: dict = Depends(require_user)):
    me = models.user_card(user, online=True)
    now = time.time()

    friends = []
    requests_in = []
    requests_out = []
    for f in db.all(
        """SELECT * FROM friendships
           WHERE user_id = ? OR friend_id = ? ORDER BY created_at DESC""",
        user["id"], user["id"],
    ):
        other_id = f["friend_id"] if f["user_id"] == user["id"] else f["user_id"]
        other = models.user_card_by_id(
            other_id, online=hub.is_online(other_id), activity=hub.activity_of(other_id)
        )
        if not other:
            continue
        if f["status"] == "accepted":
            other["frId"] = f["id"]
            friends.append(other)
        elif f["status"] == "pending":
            entry = {"id": f["id"], "user": other}
            if f["friend_id"] == user["id"]:
                requests_in.append(entry)
            else:
                requests_out.append(entry)

    rooms = []
    invites = []
    dms = []
    unread = {}
    for row in db.all(
        """SELECT m.status AS m_status, r.* FROM members m
           JOIN rooms r ON r.id = m.room_id
           WHERE m.user_id = ? ORDER BY r.created_at ASC""",
        user["id"],
    ):
        count = models.unread_count(row["id"], user["id"])
        unread[str(row["id"])] = count
        if row["kind"] == "dm":
            other_uid = db.one(
                """SELECT user_id FROM members WHERE room_id = ? AND user_id != ? LIMIT 1""",
                row["id"], user["id"],
            )
            other = None
            if other_uid:
                other = models.user_card_by_id(
                    other_uid["user_id"],
                    online=hub.is_online(other_uid["user_id"]),
                    activity=hub.activity_of(other_uid["user_id"]),
                )
            last = db.one(
                "SELECT created_at FROM messages WHERE room_id = ? ORDER BY id DESC LIMIT 1",
                row["id"],
            )
            if other:
                dms.append({
                    "roomId": row["id"], "user": other,
                    "unread": count, "lastAt": last["created_at"] if last else row["created_at"],
                })
            continue
        if row["m_status"] == "invited":
            owner = models.user_card_by_id(row["owner_id"])
            invites.append({
                "roomId": row["id"], "name": row["name"],
                "topic": row["topic"], "inviter": owner,
            })
            continue
        pb = db.one("SELECT playing, video_id FROM playback WHERE room_id = ?", row["id"])
        rooms.append({
            **models.room_dict(row),
            "unread": count,
            "live": {
                "music": bool(pb and pb["playing"] and pb["video_id"]),
                "voice": len(hub.VOICE.get(row["id"], {})),
            },
        })

    dms.sort(key=lambda d: d["lastAt"], reverse=True)

    return {
        "user": me,
        "friends": friends,
        "requestsIn": requests_in,
        "requestsOut": requests_out,
        "rooms": rooms,
        "invites": invites,
        "dms": dms,
        "unread": unread,
        "serverTime": now,
    }


@router.post("/friends/requests")
async def create_friend_request(
    payload: dict = Body(...), user: dict = Depends(require_user),
):
    if not check(f"freq:{user['id']}", 15, 300):
        raise HTTPException(429, "Whoa there. Let the spuds breathe.")
    query = str(payload.get("query") or "").strip()
    if not query or len(query) > 120:
        raise HTTPException(400, "Enter a username or email to search for.")
    target = db.one("SELECT * FROM users WHERE username = ? OR email = ?", query, query)
    if not target:
        raise HTTPException(404, "No spud found with that username or email.")
    if target["id"] == user["id"]:
        raise HTTPException(400, "You're already friends with yourself. Deep.")

    existing = db.one(
        """SELECT * FROM friendships WHERE
           (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)""",
        user["id"], target["id"], target["id"], user["id"],
    )
    if existing:
        if existing["status"] == "accepted":
            raise HTTPException(409, "You're already spuds.")
        if existing["user_id"] == user["id"]:
            raise HTTPException(409, "Friend request already planted.")
        # they already asked you — accepting is the friendly move
        db.run("UPDATE friendships SET status = 'accepted' WHERE id = ?", existing["id"])
        await hub.sync_user(user["id"], "friends")
        await hub.sync_user(target["id"], "friends")
        return {"ok": True, "autoAccepted": True}

    fid = db.insert(
        """INSERT INTO friendships (user_id, friend_id, status, created_at)
           VALUES (?,?, 'pending', ?)""",
        user["id"], target["id"], time.time(),
    )
    await hub.sync_user(target["id"], "friends")
    return {"ok": True, "id": fid}


@router.post("/friends/requests/{fid}/accept")
async def accept_request(fid: int, user: dict = Depends(require_user)):
    fr = db.one("SELECT * FROM friendships WHERE id = ?", fid)
    if not fr or fr["friend_id"] != user["id"] or fr["status"] != "pending":
        raise HTTPException(404, "That friend request doesn't exist.")
    db.run("UPDATE friendships SET status = 'accepted' WHERE id = ?", fid)
    await hub.sync_user(user["id"], "friends")
    await hub.sync_user(fr["user_id"], "friends")
    await hub.send_user(fr["user_id"], {
        "type": "toast", "level": "info",
        "text": f"{user['display_name']} accepted your friend request. You're spuds now!",
    })
    return {"ok": True}


@router.post("/friends/requests/{fid}/decline")
async def decline_request(fid: int, user: dict = Depends(require_user)):
    fr = db.one("SELECT * FROM friendships WHERE id = ?", fid)
    if not fr or fr["friend_id"] != user["id"] or fr["status"] != "pending":
        raise HTTPException(404, "That friend request doesn't exist.")
    db.run("DELETE FROM friendships WHERE id = ?", fid)
    return {"ok": True}


@router.delete("/friends/requests/{fid}")
async def cancel_request(fid: int, user: dict = Depends(require_user)):
    fr = db.one("SELECT * FROM friendships WHERE id = ?", fid)
    if not fr or fr["user_id"] != user["id"] or fr["status"] != "pending":
        raise HTTPException(404, "That friend request doesn't exist.")
    db.run("DELETE FROM friendships WHERE id = ?", fid)
    await hub.sync_user(fr["friend_id"], "friends")
    return {"ok": True}


@router.delete("/friends/{fid}")
async def remove_friend(fid: int, user: dict = Depends(require_user)):
    fr = db.one(
        """SELECT * FROM friendships WHERE id = ? AND status = 'accepted'
           AND (user_id = ? OR friend_id = ?)""",
        fid, user["id"], user["id"],
    )
    if not fr:
        raise HTTPException(404, "That friendship doesn't exist.")
    db.run("DELETE FROM friendships WHERE id = ?", fid)
    await hub.sync_user(user["id"], "friends")
    await hub.sync_user(fr["friend_id"] if fr["user_id"] == user["id"] else fr["user_id"], "friends")
    return {"ok": True}
