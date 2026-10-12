"""WebSocket message handlers (chat, presence, voice signaling, music control)."""
import time

from . import db, hub, models, player
from .config import MAX_MESSAGE_LEN

ALLOWED_REACTION_EMOJI = {"👍", "❤️", "😂", "🥔", "🔥", "😭", "🎉", "👀", "😮", "🫡"}


def _now() -> float:
    return time.time()


def _member_of(user_id: int, room_id) -> dict | None:
    if not isinstance(room_id, int):
        return None
    return db.one(
        "SELECT * FROM members WHERE room_id = ? AND user_id = ? AND status = 'active'",
        room_id, user_id,
    )


def _room_of(room_id: int):
    return db.one("SELECT * FROM rooms WHERE id = ?", room_id)


async def _toast(conn, text: str, level: str = "error") -> None:
    await hub.send(conn, {"type": "toast", "level": level, "text": text})


# --- lifecycle -----------------------------------------------------------------

async def handle_room_enter(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    room = _room_of(room_id) if isinstance(room_id, int) else None
    if not room or not _member_of(conn.user_id, room_id):
        await _toast(conn, "You don't have access to that room.")
        return

    await player.reconcile(room_id)
    hub.set_viewing(conn, room_id)

    latest = db.one(
        "SELECT COALESCE(MAX(id), 0) AS m FROM messages WHERE room_id = ?", room_id
    )["m"]
    db.run(
        "UPDATE members SET last_read_id = ? WHERE room_id = ? AND user_id = ?",
        latest, room_id, conn.user_id,
    )
    db.run("UPDATE users SET last_seen = ? WHERE id = ?", _now(), conn.user_id)

    await hub.send(conn, {
        "type": "room.entered",
        "roomId": room_id,
        "room": models.room_dict(room, include_code=True),
        "members": hub.room_member_cards(room_id),
        "music": player.snapshot(room_id),
        "voice": hub.voice_state(room_id),
    })
    await hub.send_user(conn.user_id, {
        "type": "unread.update", "roomId": room_id, "count": 0,
    })
    await hub.broadcast_room_members(room_id)
    await hub.broadcast_presence(conn.user_id)


async def handle_room_exit(conn: hub.Conn, data: dict) -> None:
    hub.set_viewing(conn, None)
    await hub.broadcast_presence(conn.user_id)


async def handle_room_read(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    if not _member_of(conn.user_id, room_id):
        return
    latest = db.one(
        "SELECT COALESCE(MAX(id), 0) AS m FROM messages WHERE room_id = ?", room_id
    )["m"]
    db.run(
        "UPDATE members SET last_read_id = ? WHERE room_id = ? AND user_id = ?",
        latest, room_id, conn.user_id,
    )
    await hub.send_user(conn.user_id, {
        "type": "unread.update", "roomId": room_id,
        "count": models.unread_count(room_id, conn.user_id),
    })


# --- chat ------------------------------------------------------------------------

async def handle_chat_send(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    content = data.get("content")
    if not isinstance(content, str):
        return
    content = content.strip()
    if not content or len(content) > MAX_MESSAGE_LEN:
        await _toast(conn, "That message is too long (or too empty).")
        return
    if not _member_of(conn.user_id, room_id):
        return
    reply_to = data.get("replyTo")
    if reply_to is not None:
        if not isinstance(reply_to, int) or not db.one(
            "SELECT 1 FROM messages WHERE id = ? AND room_id = ?", reply_to, room_id
        ):
            reply_to = None

    mid = db.insert(
        """INSERT INTO messages (room_id, user_id, kind, content, reply_to, created_at)
           VALUES (?, ?, 'text', ?, ?, ?)""",
        room_id, conn.user_id, content, reply_to, _now(),
    )
    row = db.one("SELECT * FROM messages WHERE id = ?", mid)
    await hub.deliver_message(room_id, models.message_dict(row))


async def handle_chat_typing(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    on = bool(data.get("on", True))
    if not _member_of(conn.user_id, room_id):
        return
    msg = {
        "type": "typing", "roomId": room_id,
        "userId": conn.user_id, "name": conn.user["display_name"], "on": on,
    }
    for uid in list(hub.VIEWERS.get(room_id, ())):
        if uid != conn.user_id:
            await hub.send_user(uid, msg)


async def _message_of_user(message_id) -> dict | None:
    if not isinstance(message_id, int):
        return None
    return db.one("SELECT * FROM messages WHERE id = ?", message_id)


async def handle_chat_edit(conn: hub.Conn, data: dict) -> None:
    row = await _message_of_user(data.get("messageId"))
    if not row or row["user_id"] != conn.user_id or row["deleted_at"]:
        return
    content = data.get("content")
    if not isinstance(content, str):
        return
    content = content.strip()
    if not content or len(content) > MAX_MESSAGE_LEN:
        return
    db.run(
        "UPDATE messages SET content = ?, edited_at = ? WHERE id = ?",
        content, _now(), row["id"],
    )
    updated = db.one("SELECT * FROM messages WHERE id = ?", row["id"])
    await hub.broadcast_members(
        row["room_id"], {"type": "message.updated", "message": models.message_dict(updated)}
    )


async def handle_chat_delete(conn: hub.Conn, data: dict) -> None:
    row = await _message_of_user(data.get("messageId"))
    if not row or row["user_id"] != conn.user_id or row["deleted_at"]:
        return
    db.run(
        "UPDATE messages SET deleted_at = ?, content = '' WHERE id = ?", _now(), row["id"]
    )
    db.run("DELETE FROM reactions WHERE message_id = ?", row["id"])
    updated = db.one("SELECT * FROM messages WHERE id = ?", row["id"])
    await hub.broadcast_members(
        row["room_id"], {"type": "message.updated", "message": models.message_dict(updated)}
    )


async def handle_chat_react(conn: hub.Conn, data: dict) -> None:
    row = await _message_of_user(data.get("messageId"))
    emoji = data.get("emoji")
    if not row or row["deleted_at"] or emoji not in ALLOWED_REACTION_EMOJI:
        return
    if not _member_of(conn.user_id, row["room_id"]):
        return
    existing = db.one(
        "SELECT id FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
        row["id"], conn.user_id, emoji,
    )
    if existing:
        db.run("DELETE FROM reactions WHERE id = ?", existing["id"])
    else:
        db.run(
            "INSERT OR IGNORE INTO reactions (message_id, user_id, emoji) VALUES (?,?,?)",
            row["id"], conn.user_id, emoji,
        )
    updated = db.one("SELECT * FROM messages WHERE id = ?", row["id"])
    await hub.broadcast_members(
        row["room_id"], {"type": "message.updated", "message": models.message_dict(updated)}
    )


# --- voice -----------------------------------------------------------------------

async def handle_voice_join(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    if not _member_of(conn.user_id, room_id) or not _room_of(room_id):
        await _toast(conn, "Join the room before hopping into voice.")
        return
    if conn.voice_room == room_id:
        await hub.send(conn, {"type": "voice.state", **hub.voice_state(room_id)})
        return
    if conn.voice_room is not None:
        await hub.voice_remove(conn.voice_room, conn.user_id)
        conn.voice_room = None
    conn.voice_room = room_id
    await hub.voice_add(
        room_id, conn.user_id,
        muted=bool(data.get("muted")),
        listener=bool(data.get("listener")),
    )
    await hub.send(conn, {"type": "voice.state", **hub.voice_state(room_id)})


async def handle_voice_leave(conn: hub.Conn, data: dict) -> None:
    room_id = conn.voice_room
    if room_id is not None:
        conn.voice_room = None
        await hub.voice_remove(room_id, conn.user_id)


async def handle_voice_mute(conn: hub.Conn, data: dict) -> None:
    if conn.voice_room is not None:
        await hub.voice_set_muted(conn.voice_room, conn.user_id, bool(data.get("muted")))


async def handle_voice_deafen(conn: hub.Conn, data: dict) -> None:
    if conn.voice_room is not None:
        await hub.voice_set_deafened(conn.voice_room, conn.user_id, bool(data.get("deafened")))


async def handle_voice_hand(conn: hub.Conn, data: dict) -> None:
    if conn.voice_room is not None:
        await hub.voice_set_raised(conn.voice_room, conn.user_id, bool(data.get("raised")))


async def handle_voice_speaking(conn: hub.Conn, data: dict) -> None:
    if conn.voice_room is not None:
        await hub.voice_set_speaking(conn.voice_room, conn.user_id, bool(data.get("speaking")))


# --- WebRTC relay ------------------------------------------------------------------

async def handle_rtc_offer(conn: hub.Conn, data: dict) -> None:
    await hub.rtc_relay(conn, "offer", data)


async def handle_rtc_answer(conn: hub.Conn, data: dict) -> None:
    await hub.rtc_relay(conn, "answer", data)


async def handle_rtc_ice(conn: hub.Conn, data: dict) -> None:
    await hub.rtc_relay(conn, "ice", data)


# --- music --------------------------------------------------------------------------

async def handle_music_control(conn: hub.Conn, data: dict) -> None:
    room_id = data.get("roomId")
    action = data.get("action")
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    if not isinstance(room_id, int) or not isinstance(action, str):
        return
    try:
        await player.control(room_id, conn.user_id, action, params)
    except player.ControlError as e:
        await _toast(conn, str(e))


async def handle_music_ended(conn: hub.Conn, data: dict) -> None:
    room_id, video_id = data.get("roomId"), data.get("videoId")
    if not isinstance(room_id, int) or not isinstance(video_id, str):
        return
    if not _member_of(conn.user_id, room_id):
        return
    await player.on_ended(room_id, conn.user_id, video_id, data.get("duration"))


async def handle_music_duration(conn: hub.Conn, data: dict) -> None:
    room_id, video_id = data.get("roomId"), data.get("videoId")
    if isinstance(room_id, int) and isinstance(video_id, str) and _member_of(conn.user_id, room_id):
        await player.on_duration(room_id, video_id, data.get("duration"))


async def handle_music_error(conn: hub.Conn, data: dict) -> None:
    room_id, video_id = data.get("roomId"), data.get("videoId")
    if not isinstance(room_id, int) or not isinstance(video_id, str):
        return
    if not _member_of(conn.user_id, room_id):
        return
    await player.on_error(room_id, video_id, data.get("code"))


async def handle_ping(conn: hub.Conn, data: dict) -> None:
    await hub.send(conn, {"type": "pong", "serverTime": _now()})


HANDLERS = {
    "ping": handle_ping,
    "room.enter": handle_room_enter,
    "room.exit": handle_room_exit,
    "room.read": handle_room_read,
    "chat.send": handle_chat_send,
    "chat.typing": handle_chat_typing,
    "chat.edit": handle_chat_edit,
    "chat.delete": handle_chat_delete,
    "chat.react": handle_chat_react,
    "voice.join": handle_voice_join,
    "voice.leave": handle_voice_leave,
    "voice.mute": handle_voice_mute,
    "voice.deafen": handle_voice_deafen,
    "voice.hand": handle_voice_hand,
    "voice.speaking": handle_voice_speaking,
    "rtc.offer": handle_rtc_offer,
    "rtc.answer": handle_rtc_answer,
    "rtc.ice": handle_rtc_ice,
    "music.control": handle_music_control,
    "music.ended": handle_music_ended,
    "music.duration": handle_music_duration,
    "music.error": handle_music_error,
}


async def dispatch(conn: hub.Conn, data: dict) -> None:
    handler = HANDLERS.get(data.get("type"))
    if handler is None:
        return
    try:
        await handler(conn, data)
    except Exception as e:  # never let one bad message kill the socket
        import traceback
        traceback.print_exc()
        try:
            await hub.send(conn, {"type": "toast", "level": "error",
                                  "text": "Something went sideways in the HQ. Try again."})
        except Exception:
            pass
