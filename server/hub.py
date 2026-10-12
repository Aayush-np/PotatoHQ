"""Realtime hub: WebSocket connections, presence, voice roster, event fan-out."""
import asyncio
import json
import time
import uuid

from . import db, models


class Conn:
    __slots__ = ("id", "ws", "user", "user_id", "view_room", "voice_room")

    def __init__(self, ws, user: dict):
        self.id = uuid.uuid4().hex
        self.ws = ws
        self.user = user
        self.user_id = user["id"]
        self.view_room: int | None = None
        self.voice_room: int | None = None


CONNS: dict[int, set[Conn]] = {}
VIEWERS: dict[int, set[int]] = {}
VOICE: dict[int, dict[int, dict]] = {}

_last_speaking: dict[int, float] = {}


# --- basics -------------------------------------------------------------------

def online_user_ids() -> set[int]:
    return {uid for uid, conns in CONNS.items() if conns}


def is_online(user_id: int) -> bool:
    return bool(CONNS.get(user_id))


async def send(conn: Conn, msg: dict) -> None:
    try:
        await conn.ws.send_text(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        pass


async def send_user(user_id: int, msg: dict) -> None:
    for conn in list(CONNS.get(user_id, ())):
        await send(conn, msg)


async def broadcast_members(room_id: int, msg: dict) -> None:
    """All connections of every online, active member of the room."""
    members = db.all(
        "SELECT user_id FROM members WHERE room_id = ? AND status = 'active'", room_id
    )
    for m in members:
        await send_user(m["user_id"], msg)


async def broadcast_viewers(room_id: int, msg: dict) -> None:
    for uid in list(VIEWERS.get(room_id, ())):
        await send_user(uid, msg)


def friends_of(user_id: int) -> list[int]:
    rows = db.all(
        """SELECT user_id, friend_id FROM friendships
           WHERE status = 'accepted' AND (user_id = ? OR friend_id = ?)""",
        user_id, user_id,
    )
    return [r["friend_id"] if r["user_id"] == user_id else r["user_id"] for r in rows]


async def broadcast_friends(user_id: int, msg: dict) -> None:
    for fid in friends_of(user_id):
        await send_user(fid, msg)


# --- presence ------------------------------------------------------------------

def activity_of(user_id: int) -> dict | None:
    if user_id in VOICE:
        for rid, members in VOICE.items():
            if user_id in members:
                room = db.one("SELECT id, name FROM rooms WHERE id = ?", rid)
                return {"type": "voice", "roomId": rid, "label": room["name"] if room else "a room"}
    for rid, viewers in VIEWERS.items():
        if user_id in viewers:
            room = db.one("SELECT id, name FROM rooms WHERE id = ?", rid)
            return {"type": "room", "roomId": rid, "label": room["name"] if room else "a room"}
    return None


async def presence_event(user_id: int) -> dict:
    card = models.user_card_by_id(user_id, online=is_online(user_id), activity=activity_of(user_id))
    return {"type": "presence", "user": card, "online": is_online(user_id)}


async def broadcast_presence(user_id: int) -> None:
    await broadcast_friends(user_id, await presence_event(user_id))


async def connect(conn: Conn) -> None:
    first = not CONNS.get(conn.user_id)
    CONNS.setdefault(conn.user_id, set()).add(conn)
    db.run("UPDATE users SET last_seen = ? WHERE id = ?", time.time(), conn.user_id)
    await send(conn, {
        "type": "hello",
        "serverTime": time.time(),
        "user": models.user_card(conn.user, online=True),
    })
    if first:
        await broadcast_presence(conn.user_id)


async def disconnect(conn: Conn) -> None:
    conns = CONNS.get(conn.user_id)
    if conns:
        conns.discard(conn)
        if not conns:
            CONNS.pop(conn.user_id, None)
            db.run("UPDATE users SET last_seen = ? WHERE id = ?", time.time(), conn.user_id)

    if conn.view_room is not None:
        viewers = VIEWERS.get(conn.view_room)
        if viewers:
            viewers.discard(conn.user_id)
            if not viewers:
                VIEWERS.pop(conn.view_room, None)

    if conn.voice_room is not None:
        await voice_remove(conn.voice_room, conn.user_id)
        conn.voice_room = None

    # only report offline when the user's very last connection dropped
    if not CONNS.get(conn.user_id):
        await broadcast_presence(conn.user_id)


# --- membership viewership ------------------------------------------------------

def set_viewing(conn: Conn, room_id: int | None) -> None:
    if conn.view_room is not None:
        viewers = VIEWERS.get(conn.view_room)
        if viewers:
            viewers.discard(conn.user_id)
            if not viewers:
                VIEWERS.pop(conn.view_room, None)
    conn.view_room = room_id
    if room_id is not None:
        VIEWERS.setdefault(room_id, set()).add(conn.user_id)


def room_member_cards(room_id: int) -> list[dict]:
    rows = db.all(
        """SELECT u.*, m.role, m.status FROM members m JOIN users u ON u.id = m.user_id
           WHERE m.room_id = ? ORDER BY m.joined_at""",
        room_id,
    )
    cards = []
    for u in rows:
        card = models.user_card(u, online=is_online(u["id"]), activity=activity_of(u["id"]))
        card["role"] = u["role"]
        card["memberStatus"] = u["status"]
        cards.append(card)
    return cards


async def broadcast_room_members(room_id: int) -> None:
    await broadcast_members(
        room_id, {"type": "room.members", "roomId": room_id, "members": room_member_cards(room_id)}
    )


# --- messages --------------------------------------------------------------------

async def deliver_message(room_id: int, message: dict) -> None:
    await broadcast_members(room_id, {"type": "room.message", "message": message})
    # bump unread badges for online members who aren't viewing this room
    for uid in online_user_ids():
        if uid in VIEWERS.get(room_id, ()):
            continue
        member = db.one(
            "SELECT 1 FROM members WHERE room_id = ? AND user_id = ? AND status = 'active'",
            room_id, uid,
        )
        if member:
            await send_user(uid, {
                "type": "unread.update", "roomId": room_id,
                "count": models.unread_count(room_id, uid),
            })


# --- voice ------------------------------------------------------------------------

def voice_state(room_id: int) -> dict:
    participants = []
    for uid, info in VOICE.get(room_id, {}).items():
        card = models.user_card_by_id(uid, online=True, activity=None)
        if card:
            participants.append({
                "user": card,
                "muted": info.get("muted", False),
                "speaking": info.get("speaking", False),
                "listener": info.get("listener", False),
                "deafened": info.get("deafened", False),
                "raised": info.get("raised", False),
            })
    return {"roomId": room_id, "participants": participants}


async def broadcast_voice_state(room_id: int) -> None:
    await broadcast_members(room_id, {"type": "voice.state", **voice_state(room_id)})


async def voice_add(room_id: int, user_id: int, muted: bool, listener: bool) -> None:
    VOICE.setdefault(room_id, {})[user_id] = {
        "muted": muted, "speaking": False, "listener": listener,
        "deafened": False, "raised": False,
    }
    await broadcast_voice_state(room_id)
    await broadcast_presence(user_id)


async def voice_remove(room_id: int, user_id: int) -> None:
    members = VOICE.get(room_id)
    if members and user_id in members:
        members.pop(user_id)
        if not members:
            VOICE.pop(room_id, None)
        await broadcast_voice_state(room_id)
        await broadcast_presence(user_id)


async def voice_set_muted(room_id: int, user_id: int, muted: bool) -> None:
    members = VOICE.get(room_id)
    if members and user_id in members:
        members[user_id]["muted"] = bool(muted)
        await broadcast_voice_state(room_id)


async def voice_set_deafened(room_id: int, user_id: int, deafened: bool) -> None:
    members = VOICE.get(room_id)
    if members and user_id in members:
        members[user_id]["deafened"] = bool(deafened)
        await broadcast_voice_state(room_id)


async def voice_set_raised(room_id: int, user_id: int, raised: bool) -> None:
    members = VOICE.get(room_id)
    if members and user_id in members:
        members[user_id]["raised"] = bool(raised)
        await broadcast_voice_state(room_id)


async def voice_set_speaking(room_id: int, user_id: int, speaking: bool) -> None:
    now = time.time()
    last = _last_speaking.get(user_id, 0)
    if speaking and now - last < 0.25:
        return
    _last_speaking[user_id] = now
    members = VOICE.get(room_id)
    if members and user_id in members:
        if members[user_id]["speaking"] == speaking:
            return
        members[user_id]["speaking"] = speaking
        await broadcast_viewers(room_id, {
            "type": "voice.speaking", "roomId": room_id, "userId": user_id, "speaking": speaking,
        })


async def voice_clear_user(user_id: int) -> None:
    for rid in list(VOICE.keys()):
        if user_id in VOICE[rid]:
            await voice_remove(rid, user_id)


async def rtc_relay(conn: Conn, kind: str, data: dict) -> None:
    target = data.get("to")
    if not isinstance(target, int):
        return
    room_id = conn.voice_room
    if room_id is None or target not in VOICE.get(room_id, {}):
        return
    payload = {"type": f"rtc.{kind}", "from": conn.user_id, "roomId": room_id,
               "sdp": data.get("sdp"), "candidate": data.get("candidate")}
    await send_user(target, payload)


# --- room lifecycle ----------------------------------------------------------------

async def kick_user(room_id: int, user_id: int) -> None:
    for conn in list(CONNS.get(user_id, ())):
        if conn.view_room == room_id:
            set_viewing(conn, None)
            await send(conn, {"type": "room.kicked", "roomId": room_id})
        if conn.voice_room == room_id:
            conn.voice_room = None
    await voice_remove(room_id, user_id)
    await broadcast_room_members(room_id)


async def sync_user(user_id: int, what: str = "all") -> None:
    await send_user(user_id, {"type": "sync", "what": what})


async def sync_room_members(room_id: int, what: str = "all") -> None:
    for m in db.all("SELECT user_id FROM members WHERE room_id = ? AND status='active'", room_id):
        await sync_user(m["user_id"], what)
