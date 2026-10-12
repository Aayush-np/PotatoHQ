"""Rooms, invitations, membership, DMs, and message history."""
import secrets
import time

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db, hub, models, player
from ..config import MAX_NAME_LEN, MAX_TOPIC_LEN
from ..ratelimit import check
from .auth import require_user

router = APIRouter()

JOIN_MESSAGES = [
    "{name} dug into the room.",
    "{name} rolled in like a hot potato.",
    "{name} appeared in a puff of starch.",
    "{name} found the secret entrance.",
]


def _get_room_or_404(room_id: int) -> dict:
    room = db.one("SELECT * FROM rooms WHERE id = ?", room_id)
    if not room:
        raise HTTPException(404, "That room has vanished.")
    return room


def _require_member(room_id: int, user_id: int, active_only: bool = True) -> dict:
    sql = "SELECT * FROM members WHERE room_id = ? AND user_id = ?"
    if active_only:
        sql += " AND status = 'active'"
    m = db.one(sql, room_id, user_id)
    if not m:
        raise HTTPException(403, "This is a private room — you need an invite.")
    return m


async def _system(room_id: int, content: str) -> None:
    mid = db.insert(
        """INSERT INTO messages (room_id, user_id, kind, content, created_at)
           VALUES (?, NULL, 'system', ?, ?)""",
        room_id, content[:300], time.time(),
    )
    row = db.one("SELECT * FROM messages WHERE id = ?", mid)
    if row:
        await hub.deliver_message(room_id, models.message_dict(row))


@router.post("/rooms")
async def create_room(
    payload: dict = Body(...), user: dict = Depends(require_user),
):
    if not check(f"room:{user['id']}", 10, 600):
        raise HTTPException(429, "That's a lot of rooms, spud. Wait a bit.")
    name = str(payload.get("name") or "").strip()
    topic = str(payload.get("topic") or "").strip()
    if not name or len(name) > MAX_NAME_LEN:
        raise HTTPException(400, "Room names are 1-60 characters.")
    if len(topic) > MAX_TOPIC_LEN:
        raise HTTPException(400, "Topics are 140 characters max.")

    while True:
        code = secrets.token_urlsafe(6)
        if not db.one("SELECT 1 FROM rooms WHERE invite_code = ?", code):
            break
    rid = db.insert(
        """INSERT INTO rooms (name, topic, owner_id, invite_code, kind, created_at)
           VALUES (?,?,?,?, 'room', ?)""",
        name, topic, user["id"], code, time.time(),
    )
    db.insert(
        """INSERT INTO members (room_id, user_id, role, status, joined_at)
           VALUES (?,?, 'owner', 'active', ?)""",
        rid, user["id"], time.time(),
    )

    # optionally invite friends at creation time
    invite_ids = payload.get("inviteUserIds")
    if isinstance(invite_ids, list):
        for fid in invite_ids[:20]:
            if not isinstance(fid, int):
                continue
            if db.one(
                """SELECT 1 FROM friendships WHERE status='accepted'
                   AND ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))""",
                user["id"], fid, fid, user["id"],
            ) and not db.one(
                "SELECT 1 FROM members WHERE room_id=? AND user_id=?", rid, fid
            ):
                db.insert(
                    """INSERT INTO members (room_id, user_id, role, status, joined_at)
                       VALUES (?,?, 'member', 'invited', ?)""",
                    rid, fid, time.time(),
                )
                await hub.sync_user(fid, "invites")

    room = db.one("SELECT * FROM rooms WHERE id = ?", rid)
    await hub.sync_user(user["id"], "rooms")
    return {"room": models.room_dict(room, include_code=True)}


@router.get("/rooms/{room_id}")
async def room_detail(room_id: int, user: dict = Depends(require_user)):
    room = _get_room_or_404(room_id)
    member = _require_member(room_id, user["id"], active_only=False)
    await player.reconcile(room_id)
    return {
        "room": models.room_dict(room, include_code=True),
        "members": hub.room_member_cards(room_id),
        "unread": models.unread_count(room_id, user["id"]),
        "role": member["role"],
        "memberStatus": member["status"],
    }


@router.post("/rooms/join")
async def join_by_code(payload: dict = Body(...), user: dict = Depends(require_user)):
    if not check(f"join:{user['id']}", 20, 300):
        raise HTTPException(429, "Too many join attempts. Take a breath.")
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "Enter a spud-code to join.")
    room = db.one("SELECT * FROM rooms WHERE invite_code = ?", code)
    if not room or room["kind"] != "room":
        raise HTTPException(404, "No room with that spud-code. Check with your friends.")
    member = db.one(
        "SELECT * FROM members WHERE room_id = ? AND user_id = ?", room["id"], user["id"]
    )
    if member and member["status"] == "active":
        return {"room": models.room_dict(room, include_code=True), "already": True}
    if member:
        db.run(
            "UPDATE members SET status = 'active', joined_at = ? WHERE room_id = ? AND user_id = ?",
            time.time(), room["id"], user["id"],
        )
    else:
        db.insert(
            """INSERT INTO members (room_id, user_id, role, status, joined_at)
               VALUES (?,?, 'member', 'active', ?)""",
            room["id"], user["id"], time.time(),
        )
    await _system(room["id"], JOIN_MESSAGES[secrets.randbelow(len(JOIN_MESSAGES))].format(name=user["display_name"]))
    await hub.broadcast_room_members(room["id"])
    await hub.sync_user(user["id"], "rooms")
    return {"room": models.room_dict(room, include_code=True)}


@router.post("/rooms/{room_id}/invite")
async def invite_to_room(
    room_id: int, payload: dict = Body(...), user: dict = Depends(require_user),
):
    room = _get_room_or_404(room_id)
    _require_member(room_id, user["id"])
    user_ids = payload.get("userIds")
    if not isinstance(user_ids, list) or not user_ids:
        raise HTTPException(400, "Pick at least one friend to invite.")
    invited = 0
    for uid in user_ids[:20]:
        if not isinstance(uid, int) or uid == user["id"]:
            continue
        if not db.one(
            """SELECT 1 FROM friendships WHERE status='accepted'
               AND ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))""",
            user["id"], uid, uid, user["id"],
        ):
            continue  # only friends can be invited
        if db.one("SELECT 1 FROM members WHERE room_id=? AND user_id=?", room_id, uid):
            continue
        db.insert(
            """INSERT INTO members (room_id, user_id, role, status, joined_at)
               VALUES (?,?, 'member', 'invited', ?)""",
            room_id, uid, time.time(),
        )
        await hub.sync_user(uid, "invites")
        invited += 1
    if not invited:
        raise HTTPException(400, "Those spuds are already members — or not your friends yet.")
    await hub.broadcast_room_members(room_id)
    return {"ok": True, "invited": invited}


@router.post("/rooms/{room_id}/invites/accept")
async def accept_invite(room_id: int, user: dict = Depends(require_user)):
    _get_room_or_404(room_id)
    member = _require_member(room_id, user["id"], active_only=False)
    if member["status"] != "invited":
        raise HTTPException(400, "You're not invited to that room (or already in it).")
    db.run(
        "UPDATE members SET status = 'active', joined_at = ? WHERE room_id = ? AND user_id = ?",
        time.time(), room_id, user["id"],
    )
    await _system(room_id, JOIN_MESSAGES[secrets.randbelow(len(JOIN_MESSAGES))].format(name=user["display_name"]))
    await hub.broadcast_room_members(room_id)
    await hub.sync_user(user["id"], "rooms")
    return {"ok": True}


@router.post("/rooms/{room_id}/invites/decline")
async def decline_invite(room_id: int, user: dict = Depends(require_user)):
    member = db.one(
        "SELECT * FROM members WHERE room_id = ? AND user_id = ? AND status = 'invited'",
        room_id, user["id"],
    )
    if not member:
        raise HTTPException(404, "No pending invite for that room.")
    db.run("DELETE FROM members WHERE room_id = ? AND user_id = ?", room_id, user["id"])
    await hub.sync_user(user["id"], "invites")
    return {"ok": True}


@router.post("/rooms/{room_id}/leave")
async def leave_room(room_id: int, user: dict = Depends(require_user)):
    room = _get_room_or_404(room_id)
    member = _require_member(room_id, user["id"], active_only=False)
    if member["role"] == "owner":
        raise HTTPException(400, "Owners can't leave — delete the room instead.")
    db.run("DELETE FROM members WHERE room_id = ? AND user_id = ?", room_id, user["id"])
    for conn in list(hub.CONNS.get(user["id"], ())):
        if conn.view_room == room_id:
            hub.set_viewing(conn, None)
            await hub.send(conn, {"type": "room.kicked", "roomId": room_id, "reason": "left"})
        if conn.voice_room == room_id:
            conn.voice_room = None
    await hub.voice_remove(room_id, user["id"])
    await _system(room_id, f"{user['display_name']} wandered off.")
    await hub.broadcast_room_members(room_id)
    await hub.sync_user(user["id"], "rooms")
    return {"ok": True}


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: int, user: dict = Depends(require_user)):
    room = _get_room_or_404(room_id)
    if room["owner_id"] != user["id"]:
        raise HTTPException(403, "Only the owner can demolish the room.")
    await hub.broadcast_members(room_id, {"type": "room.deleted", "roomId": room_id})
    player.on_room_deleted(room_id)
    member_ids = [
        m["user_id"] for m in db.all("SELECT user_id FROM members WHERE room_id = ?", room_id)
    ]
    db.run("DELETE FROM reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)", room_id)
    db.run("DELETE FROM messages WHERE room_id = ?", room_id)
    db.run("DELETE FROM members WHERE room_id = ?", room_id)
    db.run("DELETE FROM rooms WHERE id = ?", room_id)
    for uid in member_ids:
        await hub.sync_user(uid, "rooms")
    return {"ok": True}


@router.post("/rooms/{room_id}/kick")
async def kick_member(
    room_id: int, payload: dict = Body(...), user: dict = Depends(require_user),
):
    room = _get_room_or_404(room_id)
    if room["owner_id"] != user["id"]:
        raise HTTPException(403, "Only the owner can kick spuds out.")
    target = payload.get("userId")
    if not isinstance(target, int) or target == user["id"]:
        raise HTTPException(400, "Pick a member to kick (not yourself).")
    member = db.one(
        "SELECT * FROM members WHERE room_id = ? AND user_id = ? AND status = 'active'",
        room_id, target,
    )
    if not member:
        raise HTTPException(404, "That spud isn't in the room.")
    db.run("DELETE FROM members WHERE room_id = ? AND user_id = ?", room_id, target)
    target_user = db.one("SELECT * FROM users WHERE id = ?", target)
    await _system(
        room_id,
        f"{target_user['display_name'] if target_user else 'A spud'} was sent back to the field.",
    )
    await hub.kick_user(room_id, target)
    await hub.sync_user(target, "rooms")
    await hub.broadcast_room_members(room_id)
    return {"ok": True}


@router.patch("/rooms/{room_id}")
async def update_room(
    room_id: int, payload: dict = Body(...), user: dict = Depends(require_user),
):
    room = _get_room_or_404(room_id)
    if room["owner_id"] != user["id"]:
        raise HTTPException(403, "Only the owner can redecorate.")
    name = payload.get("name")
    if name is not None:
        name = str(name).strip()
        if not name or len(name) > MAX_NAME_LEN:
            raise HTTPException(400, "Room names are 1-60 characters.")
        db.run("UPDATE rooms SET name = ? WHERE id = ?", name, room_id)
    topic = payload.get("topic")
    if topic is not None:
        topic = str(topic).strip()
        if len(topic) > MAX_TOPIC_LEN:
            raise HTTPException(400, "Topics are 140 characters max.")
        db.run("UPDATE rooms SET topic = ? WHERE id = ?", topic, room_id)
    music_mode = payload.get("musicMode")
    if music_mode is not None:
        if music_mode not in ("owner", "shared"):
            raise HTTPException(400, "Music mode must be 'owner' or 'shared'.")
        db.run("UPDATE rooms SET music_mode = ? WHERE id = ?", music_mode, room_id)
    fresh = db.one("SELECT * FROM rooms WHERE id = ?", room_id)
    await hub.broadcast_members(
        room_id, {"type": "room.updated", "roomId": room_id,
                  "room": models.room_dict(fresh, include_code=True)}
    )
    await hub.sync_room_members(room_id, "rooms")
    return {"room": models.room_dict(fresh, include_code=True)}


@router.post("/dm")
async def open_dm(payload: dict = Body(...), user: dict = Depends(require_user)):
    target = payload.get("userId")
    if not isinstance(target, int) or target == user["id"]:
        raise HTTPException(400, "Pick a friend to message.")
    if not db.one(
        """SELECT 1 FROM friendships WHERE status='accepted'
           AND ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))""",
        user["id"], target, target, user["id"],
    ):
        raise HTTPException(403, "You can only DM your spuds (accepted friends).")
    other = db.one("SELECT * FROM users WHERE id = ?", target)
    if not other:
        raise HTTPException(404, "No such spud.")

    existing = db.one(
        """SELECT r.id FROM rooms r
           JOIN members a ON a.room_id = r.id AND a.user_id = ?
           JOIN members b ON b.room_id = r.id AND b.user_id = ?
           WHERE r.kind = 'dm' LIMIT 1""",
        user["id"], target,
    )
    if existing:
        return {"roomId": existing["id"], "created": False}
    rid = db.insert(
        """INSERT INTO rooms (name, topic, owner_id, invite_code, kind, created_at)
           VALUES ('', '', ?, ?, 'dm', ?)""",
        user["id"], secrets.token_urlsafe(8), time.time(),
    )
    now = time.time()
    db.insert(
        "INSERT INTO members (room_id, user_id, role, status, joined_at) VALUES (?,?,?,?,?)",
        rid, user["id"], "member", "active", now,
    )
    db.insert(
        "INSERT INTO members (room_id, user_id, role, status, joined_at) VALUES (?,?,?,?,?)",
        rid, target, "member", "active", now,
    )
    await hub.sync_user(target, "rooms")
    return {"roomId": rid, "created": True}


@router.get("/rooms/{room_id}/messages")
async def message_history(
    room_id: int, before: int = 0, limit: int = 50, user: dict = Depends(require_user),
):
    _get_room_or_404(room_id)
    _require_member(room_id, user["id"], active_only=False)
    limit = max(1, min(limit, 100))
    if before:
        rows = db.all(
            """SELECT * FROM messages WHERE room_id = ? AND id < ?
               ORDER BY id DESC LIMIT ?""",
            room_id, before, limit,
        )
    else:
        rows = db.all(
            "SELECT * FROM messages WHERE room_id = ? ORDER BY id DESC LIMIT ?",
            room_id, limit,
        )
    rows.reverse()
    return {"messages": models.message_dicts(rows), "hasMore": len(rows) == limit}
