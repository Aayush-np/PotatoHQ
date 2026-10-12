"""Response builders: user cards, potato avatars, room/message/track dicts."""
import hashlib
import time
import zlib

from . import db


def now() -> float:
    return time.time()


def avatar_v(user) -> int:
    """Cache-busting version for avatar URLs."""
    seed = f"{user['id']}:{user.get('avatar_path') or ''}"
    return zlib.crc32(seed.encode("utf-8")) & 0xFFFFFF


_AVATAR_COLORS = ["#C9973B", "#B58537", "#D8AC5C", "#A9792F", "#8F6527", "#E0BA6E"]


def potato_avatar_svg(uid: int) -> str:
    """Deterministic goofy potato avatar for users without an uploaded picture."""
    h = hashlib.sha256(f"potato:{uid}".encode()).hexdigest()
    color = _AVATAR_COLORS[int(h[0], 16) % len(_AVATAR_COLORS)]
    variant = int(h[1], 16) % 3
    spot1, spot2, spot3 = ("#00000022",) * 3
    cx, cy = 50, 53
    if variant == 0:  # classic smile
        face = (
            f'<circle cx="41" cy="47" r="3.4" fill="#332619"/>'
            f'<circle cx="59" cy="47" r="3.4" fill="#332619"/>'
            f'<path d="M40 59 Q50 67 60 59" stroke="#332619" stroke-width="3" fill="none" stroke-linecap="round"/>'
        )
    elif variant == 1:  # open grin
        face = (
            f'<circle cx="41" cy="46" r="3.4" fill="#332619"/>'
            f'<circle cx="59" cy="46" r="3.4" fill="#332619"/>'
            f'<path d="M39 57 Q50 70 61 57 Z" fill="#332619"/>'
            f'<path d="M42 58 Q50 65 58 58 Z" fill="#fff6e6"/>'
        )
    else:  # wink
        face = (
            f'<circle cx="41" cy="47" r="3.4" fill="#332619"/>'
            f'<path d="M55 47 Q60 44 64 48" stroke="#332619" stroke-width="3" fill="none" stroke-linecap="round"/>'
            f'<path d="M41 59 Q51 67 60 58" stroke="#332619" stroke-width="3" fill="none" stroke-linecap="round"/>'
        )
    spots = (
        f'<ellipse cx="30" cy="66" rx="6" ry="4" fill="#00000026" transform="rotate(-14 30 66)"/>'
        f'<ellipse cx="70" cy="38" rx="5" ry="3.4" fill="#00000026" transform="rotate(18 70 38)"/>'
        f'<ellipse cx="62" cy="78" rx="4.4" ry="3" fill="#0000001f" transform="rotate(8 62 78)"/>'
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Potato avatar">'
        f'<path d="M50 12 C72 12 88 30 87 53 C86 77 70 92 49 92 C28 92 13 76 13 52 C13 29 28 12 50 12 Z" fill="{color}"/>'
        f'{spots}{face}'
        "</svg>"
    )


def user_card(u: dict, online: bool = False, activity: dict | None = None) -> dict:
    return {
        "id": u["id"],
        "username": u["username"],
        "displayName": u["display_name"],
        "avatarUrl": f"/api/users/{u['id']}/avatar?v={avatar_v(u)}",
        "online": online,
        "activity": activity,
    }


def user_card_by_id(uid: int, online: bool = False, activity: dict | None = None):
    u = db.one("SELECT * FROM users WHERE id = ?", uid)
    return user_card(u, online, activity) if u else None


def track_dict(video_id, title, artist, artwork, duration) -> dict:
    return {
        "videoId": video_id,
        "title": (title or "Unknown track")[:200],
        "artist": (artist or "")[:200],
        "artwork": artwork,
        "duration": round(duration, 3) if duration else None,
    }


def queue_item_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        **track_dict(row["video_id"], row["title"], row["artist"], row["artwork"], row["duration"]),
        "addedBy": row["added_by"],
    }


def history_item_dict(row: dict) -> dict:
    return track_dict(row["video_id"], row["title"], row["artist"], row["artwork"], row["duration"])


def room_dict(r: dict, include_code: bool = False) -> dict:
    d = {
        "id": r["id"],
        "name": r["name"],
        "topic": r["topic"],
        "ownerId": r["owner_id"],
        "kind": r["kind"],
        "musicMode": r["music_mode"],
        "createdAt": r["created_at"],
    }
    if include_code:
        d["inviteCode"] = r["invite_code"]
    return d


def _reactions_for(message_ids: list[int]) -> dict[int, list[dict]]:
    if not message_ids:
        return {}
    marks = ",".join("?" * len(message_ids))
    rows = db.all(
        f"SELECT message_id, emoji, user_id FROM reactions WHERE message_id IN ({marks})",
        *message_ids,
    )
    grouped: dict[int, dict[str, list[int]]] = {}
    for r in rows:
        g = grouped.setdefault(r["message_id"], {})
        g.setdefault(r["emoji"], []).append(r["user_id"])
    out = {}
    for mid, g in grouped.items():
        out[mid] = [{"emoji": e, "users": uids} for e, uids in g.items()]
    return out


def message_dicts(rows: list[dict]) -> list[dict]:
    """Convert message rows (ascending) into wire payloads with author, reply preview, reactions."""
    mids = [r["id"] for r in rows]
    reactions = _reactions_for(mids)

    author_ids = {r["user_id"] for r in rows if r["user_id"]}
    reply_ids = {r["reply_to"] for r in rows if r["reply_to"]}
    need = reply_ids - set(mids)
    replies = {}
    if reply_ids:
        marks = ",".join("?" * len(reply_ids))
        for rr in db.all(f"SELECT * FROM messages WHERE id IN ({marks})", *reply_ids):
            replies[rr["id"]] = rr

    users = {}
    lookup_ids = author_ids | {rr["user_id"] for rr in replies.values() if rr["user_id"]}
    if lookup_ids:
        marks = ",".join("?" * len(lookup_ids))
        for u in db.all(f"SELECT * FROM users WHERE id IN ({marks})", *lookup_ids):
            users[u["id"]] = u

    out = []
    for r in rows:
        author = users.get(r["user_id"])
        reply = None
        if r["reply_to"]:
            rr = replies.get(r["reply_to"])
            if rr:
                au = users.get(rr["user_id"])
                reply = {
                    "id": rr["id"],
                    "authorName": (au["display_name"] if au else "A spud"),
                    "snippet": (rr["content"] or "")[:90],
                    "deleted": rr["deleted_at"] is not None,
                }
        out.append({
            "id": r["id"],
            "roomId": r["room_id"],
            "kind": r["kind"],
            "content": r["content"],
            "createdAt": r["created_at"],
            "editedAt": r["edited_at"],
            "deleted": r["deleted_at"] is not None,
            "author": user_card(author) if author else None,
            "replyTo": reply,
            "reactions": reactions.get(r["id"], []),
        })
    return out


def message_dict(row: dict) -> dict:
    return message_dicts([row])[0]


def unread_count(room_id: int, user_id: int) -> int:
    m = db.one(
        "SELECT last_read_id FROM members WHERE room_id = ? AND user_id = ?", room_id, user_id
    )
    if not m:
        return 0
    r = db.one(
        """SELECT COUNT(*) AS c FROM messages
           WHERE room_id = ? AND id > ? AND deleted_at IS NULL""",
        room_id, m["last_read_id"],
    )
    return r["c"] if r else 0
