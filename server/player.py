"""Authoritative shared music playback state.

The server owns the truth for every room: current track, position, playing
flag, queue, autoplay and repeat/shuffle config. Position is stored as
`position @ anchor` (server epoch seconds), so `expected = position + (now -
anchor)` while playing. A per-room ticker task advances tracks at the end of
their duration; client "ended" reports are accepted as a fallback when a
client's real duration disagrees with metadata, guarded by the room lock +
version counter so concurrent end reports can't double-advance.

Broadcast fan-out goes through the hub (all *member* connections, not just
current viewers) so the global player bar keeps working while a user browses
elsewhere in the app.
"""
import asyncio
import random
import time
from collections import deque

from . import db, hub, models, ytm
from .config import (
    AUTOPLAY_RECENT, END_EPSILON, MAX_QUEUE_ITEMS, TICK_BROADCAST_EVERY, TICK_INTERVAL,
)

SESSIONS: dict[int, dict] = {}


class ControlError(Exception):
    def __init__(self, message: str, code: str = "bad_request"):
        super().__init__(message)
        self.code = code


def now() -> float:
    return time.time()


def ensure(room_id: int) -> dict:
    s = SESSIONS.get(room_id)
    if s is None:
        s = {
            "lock": asyncio.Lock(),
            "task": None,
            "task_holder": None,
            "failed": set(),
            "recent": deque(maxlen=AUTOPLAY_RECENT),
            "reconciled": False,
        }
        SESSIONS[room_id] = s
    return s


def expected_position(row: dict) -> float:
    if not row or not row["playing"]:
        return row["position"] if row else 0.0
    return row["position"] + max(0.0, now() - row["anchor"])


def _playback_row(room_id: int):
    return db.one("SELECT * FROM playback WHERE room_id = ?", room_id)


def _ensure_playback_row(room_id: int) -> dict:
    row = _playback_row(room_id)
    if row is None:
        db.run(
            """INSERT OR IGNORE INTO playback
               (room_id, position, anchor, updated_at) VALUES (?, 0, ?, ?)""",
            room_id, now(), now(),
        )
        row = _playback_row(room_id)
    return row


def _track_of_row(row: dict) -> dict | None:
    if not row or not row["video_id"]:
        return None
    return models.track_dict(row["video_id"], row["title"], row["artist"], row["artwork"], row["duration"])


def snapshot(room_id: int) -> dict:
    """Full music payload for a room (state + queue + history + mode)."""
    row = _playback_row(room_id)
    room = db.one("SELECT music_mode FROM rooms WHERE id = ?", room_id)
    queue = [
        models.queue_item_dict(q)
        for q in db.all(
            """SELECT * FROM queue_items WHERE room_id = ? AND played_at IS NULL
               ORDER BY position LIMIT 200""",
            room_id,
        )
    ]
    history = [
        models.history_item_dict(h)
        for h in db.all(
            """SELECT * FROM queue_items WHERE room_id = ? AND played_at IS NOT NULL
               ORDER BY played_at DESC LIMIT 12""",
            room_id,
        )
    ]
    if row is None:
        state = {
            "current": None, "playing": False, "position": 0.0, "anchor": now(),
            "serverTime": now(), "version": 0, "repeat": "off", "shuffle": False,
            "autoplay": True,
        }
    else:
        state = {
            "current": _track_of_row(row),
            "playing": bool(row["playing"]),
            "position": row["position"],
            "anchor": row["anchor"],
            "serverTime": now(),
            "version": row["version"],
            "repeat": row["repeat"],
            "shuffle": bool(row["shuffle"]),
            "autoplay": bool(row["autoplay"]),
        }
    return {"state": state, "queue": queue, "history": history, "mode": room["music_mode"] if room else "shared"}


async def broadcast_state(room_id: int) -> None:
    await hub.broadcast_members(
        room_id, {"type": "music.state", "roomId": room_id, **snapshot(room_id)}
    )


async def reconcile(room_id: int) -> None:
    """Recover stale playback state (e.g. after a server restart)."""
    s = ensure(room_id)
    if s["reconciled"]:
        return
    s["reconciled"] = True
    async with s["lock"]:
        row = _playback_row(room_id)
        if row and row["playing"] and row["video_id"]:
            exp = expected_position(row)
            if row["duration"] and exp >= row["duration"] - END_EPSILON:
                await _advance_locked(room_id, "ended")
            elif not row["duration"] and now() - row["anchor"] > 7200:
                # unknown duration and a very long gap: park it paused
                _write(row, position=exp, playing=0, anchor=now())
            else:
                _start_ticker(room_id)


def _write(row: dict, *, video_id=None, title=None, artist=None, artwork=None,
           duration=None, position=None, playing=None, anchor=None, repeat=None,
           shuffle=None, autoplay=None, bump=True) -> None:
    sets = ["updated_at = ?"]
    params: list = [now()]
    if video_id is not None:
        sets += ["video_id = ?", "title = ?", "artist = ?", "artwork = ?", "duration = ?"]
        params += [video_id, title, artist, artwork, duration]
    if position is not None:
        sets.append("position = ?"); params.append(round(position, 3))
    if playing is not None:
        sets.append("playing = ?"); params.append(1 if playing else 0)
    if anchor is not None:
        sets.append("anchor = ?"); params.append(round(anchor, 3))
    if repeat is not None:
        sets.append("repeat = ?"); params.append(repeat)
    if shuffle is not None:
        sets.append("shuffle = ?"); params.append(1 if shuffle else 0)
    if autoplay is not None:
        sets.append("autoplay = ?"); params.append(1 if autoplay else 0)
    if bump:
        sets.append("version = version + 1")
    params.append(row["room_id"])
    db.run(f"UPDATE playback SET {', '.join(sets)} WHERE room_id = ?", *params)


def _start_ticker(room_id: int) -> None:
    s = ensure(room_id)
    if s["task"] is None or s["task"].done():
        s["task"] = asyncio.create_task(_ticker(room_id))


def _current(row: dict) -> dict | None:
    return _track_of_row(row)


def _validate_track(t) -> dict:
    if not isinstance(t, dict):
        raise ControlError("Track payload is malformed")
    vid = t.get("videoId")
    if not isinstance(vid, str) or not ytm.VIDEO_ID_RE.fullmatch(vid):
        raise ControlError("That track ID doesn't look right")
    title = t.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ControlError("Track is missing a title")
    artist = t.get("artist") or ""
    artwork = t.get("artwork")
    if artwork is not None and (not isinstance(artwork, str) or not artwork.startswith(("http://", "https://"))):
        artwork = None
    artwork = artwork[:500] if artwork else None
    duration = t.get("duration")
    if duration is not None:
        try:
            duration = round(float(duration), 3)
            if not 0 < duration < 60 * 60 * 12:
                duration = None
        except (TypeError, ValueError):
            duration = None
    return models.track_dict(vid, title.strip()[:200], str(artist)[:200], artwork, duration)


async def _post_system(room_id: int, content: str) -> None:
    mid = db.insert(
        """INSERT INTO messages (room_id, user_id, kind, content, created_at)
           VALUES (?, NULL, 'system', ?, ?)""",
        room_id, content[:300], now(),
    )
    row = db.one("SELECT * FROM messages WHERE id = ?", mid)
    if row:
        await hub.deliver_message(room_id, models.message_dict(row))


def _history_append(room_id: int, track: dict) -> None:
    db.run(
        """INSERT INTO queue_items
           (room_id, video_id, title, artist, artwork, duration, added_by, position, added_at, played_at)
           VALUES (?,?,?,?,?,?,?,0,?,?)""",
        room_id, track["videoId"], track["title"], track["artist"], track["artwork"],
        track["duration"], 0, now(), now(),
    )
    # cap history at 40 rows per room
    db.run(
        """DELETE FROM queue_items WHERE room_id = ? AND played_at IS NOT NULL AND id NOT IN
           (SELECT id FROM queue_items WHERE room_id = ? AND played_at IS NOT NULL
            ORDER BY played_at DESC LIMIT 40)""",
        room_id, room_id,
    )


def _pop_queue_head(room_id: int, shuffle: bool) -> dict | None:
    rows = db.all(
        "SELECT * FROM queue_items WHERE room_id = ? AND played_at IS NULL ORDER BY position",
        room_id,
    )
    if not rows:
        return None
    row = random.choice(rows) if shuffle else rows[0]
    db.run("DELETE FROM queue_items WHERE id = ?", row["id"])
    return models.queue_item_dict(row)


async def _pick_autoplay(room_id: int, seed: dict) -> dict | None:
    s = ensure(room_id)
    try:
        candidates = await ytm.related_tracks(seed["videoId"], limit=20)
    except Exception:
        return None
    for t in candidates:
        vid = t["videoId"]
        if vid == seed["videoId"] or vid in s["recent"] or vid in s["failed"]:
            continue
        return t
    return None


async def _advance_locked(room_id: int, reason: str) -> None:
    """Move to the next track. Must be called under the room lock."""
    row = _ensure_playback_row(room_id)
    s = ensure(room_id)
    cur = _current(row)
    if cur:
        _history_append(room_id, cur)
        s["recent"].append(cur["videoId"])

    next_track = None
    if reason == "ended" and row["repeat"] == "one" and cur:
        next_track = cur
    else:
        next_track = _pop_queue_head(room_id, bool(row["shuffle"]))
        if next_track is None and cur:
            if row["autoplay"]:
                next_track = await _pick_autoplay(room_id, cur)
                if next_track is None and row["repeat"] == "all":
                    next_track = _refill_from_history(room_id)
            elif row["repeat"] == "all":
                next_track = _refill_from_history(room_id)

    if next_track:
        _write(row, video_id=next_track["videoId"], title=next_track["title"],
               artist=next_track["artist"], artwork=next_track["artwork"],
               duration=next_track["duration"], position=0.0, playing=1, anchor=now())
        if reason == "error":
            await _post_system(room_id, f"That track isn't playable in the HQ — skipping to {next_track['title']}.")
        _start_ticker(room_id)
    else:
        _write(row, video_id="", title="", artist="", artwork="", duration=None,
               position=0.0, playing=0, anchor=now())
        if reason == "error":
            await _post_system(room_id, "That track isn't playable in the HQ and there's nothing queued.")
        elif reason == "ended":
            await _post_system(room_id, "The spud ran out of tunes. Queue something else!")
    await broadcast_state(room_id)


def _refill_from_history(room_id: int) -> dict | None:
    rows = db.all(
        """SELECT * FROM queue_items WHERE room_id = ? AND played_at IS NOT NULL
           ORDER BY played_at ASC LIMIT 40""",
        room_id,
    )
    if not rows:
        return None
    base = now()
    for i, r in enumerate(rows):
        db.run(
            "UPDATE queue_items SET played_at = NULL, position = ? WHERE id = ?",
            base + i, r["id"],
        )
    db.run("DELETE FROM queue_items WHERE id = ?", rows[0]["id"])
    return models.queue_item_dict(rows[0])


async def control(room_id: int, user_id: int, action: str, params: dict) -> dict:
    room = db.one("SELECT * FROM rooms WHERE id = ?", room_id)
    if not room or room["kind"] != "room":
        raise ControlError("That room doesn't exist", "not_found")
    member = db.one(
        "SELECT * FROM members WHERE room_id = ? AND user_id = ? AND status = 'active'",
        room_id, user_id,
    )
    if not member:
        raise ControlError("You're not a member of that room", "forbidden")
    is_owner = room["owner_id"] == user_id
    allowed = is_owner or room["music_mode"] == "shared"

    if action == "set_mode":
        if not is_owner:
            raise ControlError("Only the room owner can change music permissions", "forbidden")
    elif action == "add":
        pass  # adding follows the same permission rule as other controls
    elif not allowed:
        raise ControlError("The room owner has the aux cable right now", "forbidden")

    s = ensure(room_id)
    async with s["lock"]:
        result = await _apply(room_id, room, user_id, action, params, allowed)
    await broadcast_state(room_id)
    if action == "set_mode":
        await hub.broadcast_members(
            room_id,
            {"type": "room.updated", "roomId": room_id,
             "room": models.room_dict(room, include_code=True)},
        )
    return result


async def _apply(room_id: int, room: dict, user_id: int, action: str, params: dict, allowed: bool) -> dict:
    row = _ensure_playback_row(room_id)

    if action == "add":
        tracks_raw = params.get("tracks") if isinstance(params.get("tracks"), list) else None
        if tracks_raw is None:
            tracks_raw = [params.get("track")]
        tracks = [_validate_track(t) for t in tracks_raw if t is not None]
        if not tracks:
            raise ControlError("No track to add")
        queued = db.one(
            "SELECT COUNT(*) AS c FROM queue_items WHERE room_id = ? AND played_at IS NULL",
            room_id,
        )["c"]
        if queued + len(tracks) > MAX_QUEUE_ITEMS:
            raise ControlError("The queue is stuffed. Remove a track first.")
        base = db.one(
            "SELECT COALESCE(MAX(position), 0) AS p FROM queue_items WHERE room_id = ? AND played_at IS NULL",
            room_id,
        )["p"]
        for i, t in enumerate(tracks):
            db.run(
                """INSERT INTO queue_items
                   (room_id, video_id, title, artist, artwork, duration, added_by, position, added_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                room_id, t["videoId"], t["title"], t["artist"], t["artwork"], t["duration"],
                user_id, base + 1 + i, now(),
            )
        if not row["video_id"]:
            # first track in an idle room: start the party
            first = _pop_queue_head(room_id, False)
            if first:
                _write(row, video_id=first["videoId"], title=first["title"],
                       artist=first["artist"], artwork=first["artwork"],
                       duration=first["duration"], position=0.0, playing=1, anchor=now())
                _start_ticker(room_id)
        return {"added": len(tracks)}

    if action == "play":
        if row["video_id"] and not row["playing"]:
            _write(row, playing=1, anchor=now())
        elif not row["video_id"]:
            first = _pop_queue_head(room_id, False)
            if first:
                _write(row, video_id=first["videoId"], title=first["title"],
                       artist=first["artist"], artwork=first["artwork"],
                       duration=first["duration"], position=0.0, playing=1, anchor=now())
                _start_ticker(room_id)
        return {}

    if action == "pause":
        if row["playing"]:
            _write(row, position=expected_position(row), playing=0, anchor=now())
        return {}

    if action == "resume":
        if row["video_id"] and not row["playing"]:
            _write(row, playing=1, anchor=now())
            _start_ticker(room_id)
        return {}

    if action == "seek":
        try:
            pos = float(params.get("position", 0))
        except (TypeError, ValueError):
            raise ControlError("Bad seek position")
        dur = row["duration"] or 0
        if dur > 0:
            pos = max(0.0, min(pos, dur - 0.5))
        _write(row, position=pos, anchor=now())
        return {}

    if action == "skip":
        await _advance_locked(room_id, "skip")
        return {}

    if action == "prev":
        prev = db.one(
            """SELECT * FROM queue_items WHERE room_id = ? AND played_at IS NOT NULL
               ORDER BY played_at DESC LIMIT 1""",
            room_id,
        )
        if prev:
            db.run("DELETE FROM queue_items WHERE id = ?", prev["id"])
            _write(row, video_id=prev["video_id"], title=prev["title"],
                   artist=prev["artist"], artwork=prev["artwork"],
                   duration=prev["duration"], position=0.0, playing=1, anchor=now())
            s = ensure(room_id)
            if prev["video_id"] in s["recent"]:
                s["recent"].remove(prev["video_id"])
            _start_ticker(room_id)
        elif row["video_id"]:
            _write(row, position=0.0, anchor=now())
        return {}

    if action == "shuffle":
        flag = 1 if params.get("on") else 0
        _write(row, shuffle=flag, bump=False)
        return {}

    if action == "repeat":
        mode = params.get("mode")
        if mode not in ("off", "all", "one"):
            raise ControlError("Repeat mode must be off, all, or one")
        _write(row, repeat=mode, bump=False)
        return {}

    if action == "autoplay":
        flag = 1 if params.get("on") else 0
        _write(row, autoplay=flag, bump=False)
        return {}

    if action == "remove":
        item_id = params.get("itemId")
        item = db.one(
            "SELECT * FROM queue_items WHERE id = ? AND room_id = ? AND played_at IS NULL",
            item_id, room_id,
        )
        if not item:
            raise ControlError("That track already left the queue", "not_found")
        if item["added_by"] != user_id and not allowed:
            raise ControlError("Only the person who queued it (or the owner) can remove it", "forbidden")
        db.run("DELETE FROM queue_items WHERE id = ?", item_id)
        return {}

    if action == "move_top":
        item_id = params.get("itemId")
        item = db.one(
            "SELECT * FROM queue_items WHERE id = ? AND room_id = ? AND played_at IS NULL",
            item_id, room_id,
        )
        if not item:
            raise ControlError("That track isn't in the queue", "not_found")
        if item["added_by"] != user_id and not allowed:
            raise ControlError("Only the person who queued it (or the owner) can move it", "forbidden")
        lowest = db.one(
            "SELECT COALESCE(MIN(position), 0) AS p FROM queue_items WHERE room_id = ? AND played_at IS NULL",
            room_id,
        )["p"]
        db.run("UPDATE queue_items SET position = ? WHERE id = ?", lowest - 1, item_id)
        return {}

    if action == "set_mode":
        mode = params.get("mode")
        if mode not in ("owner", "shared"):
            raise ControlError("Mode must be owner or shared")
        db.run("UPDATE rooms SET music_mode = ? WHERE id = ?", mode, room_id)
        room["music_mode"] = mode
        return {}

    raise ControlError(f"Unknown control action '{action}'")


# --- client reports -----------------------------------------------------------

async def on_ended(room_id: int, user_id: int, video_id: str, duration) -> None:
    """A client's player genuinely reached the end of the video."""
    await reconcile(room_id)
    s = ensure(room_id)
    s.setdefault("ended_guard", {})
    async with s["lock"]:
        row = _playback_row(room_id)
        if not row or not row["playing"] or row["video_id"] != video_id:
            return  # stale or already advanced (version/identity guard)
        # duplicate-ended guard: several clients report the same end; the first
        # one advances, the rest must not trigger a second transition (e.g.
        # under repeat-one where the next track is the same videoId).
        now_ts = time.time()
        if now_ts - s["ended_guard"].get(video_id, 0) < 2.0:
            return
        try:
            real = float(duration)
        except (TypeError, ValueError):
            real = None
        exp = expected_position(row)
        if real and 0 < real < 60 * 60 * 12:
            if not row["duration"] or abs(row["duration"] - real) > 2:
                _write(row, duration=real, bump=False)
            # a genuine end means wall-clock time elapsed ≈ the video length
            if exp >= real - 8:
                s["ended_guard"][video_id] = now_ts
                await _advance_locked(room_id, "ended")
        elif row["duration"] and exp >= row["duration"] - END_EPSILON:
            s["ended_guard"][video_id] = now_ts
            await _advance_locked(room_id, "ended")


async def on_duration(room_id: int, video_id: str, duration) -> None:
    """Clients report the iframe player's true duration once known — this
    also proves the track actually started, so it resets the error streak."""
    try:
        real = float(duration)
    except (TypeError, ValueError):
        return
    if not 0 < real < 60 * 60 * 12:
        return
    s = ensure(room_id)
    s["error_streak"] = 0
    row = _playback_row(room_id)
    if row and row["video_id"] == video_id and (not row["duration"] or abs(row["duration"] - real) > 2):
        _write(row, duration=real, bump=False)
        if row["playing"]:
            _start_ticker(room_id)


async def on_error(room_id: int, video_id: str, code) -> None:
    """The embedded player refused the track (unavailable / not embeddable).

    Some catalogs (e.g. T-Series, many Vevo channels) block embedding
    entirely, so a bad queue or autoplay chain would otherwise error-advance
    once per second. We breathe between skips, always keep draining the
    user's own queue, and only give up when the autoplay chain alone keeps
    failing.
    """
    await reconcile(room_id)
    s = ensure(room_id)
    async with s["lock"]:
        row = _playback_row(room_id)
        if not row or row["video_id"] != video_id:
            return
        s["failed"].add(video_id)
        s["error_streak"] = s.get("error_streak", 0) + 1
        queued = db.one(
            "SELECT COUNT(*) AS c FROM queue_items WHERE room_id = ? AND played_at IS NULL",
            room_id,
        )["c"]
        if queued == 0 and s["error_streak"] >= 4:
            _write(row, video_id="", title="", artist="", artwork="", duration=None,
                   position=0.0, playing=0, anchor=now())
            await _post_system(
                room_id,
                "The autoplay radio keeps hitting tracks that can't be played here — "
                "the aux cable is resting. Queue some songs to get the jam going.",
            )
            await broadcast_state(room_id)
            return
        if s["error_streak"] >= 12:
            _write(row, video_id="", title="", artist="", artwork="", duration=None,
                   position=0.0, playing=0, anchor=now())
            await _post_system(
                room_id,
                "That's a lot of unplayable tracks in a row — the spuds gave up for now. "
                "Try different songs (some labels block embedding).",
            )
            await broadcast_state(room_id)
            return
        await asyncio.sleep(1.5)  # breather so a bad stretch doesn't strobe the room
        await _advance_locked(room_id, "error")


async def _ticker(room_id: int) -> None:
    s = ensure(room_id)
    cycles = 0
    try:
        while True:
            await asyncio.sleep(TICK_INTERVAL)
            row = _playback_row(room_id)
            if not row or not row["playing"] or not row["video_id"]:
                break
            cycles += 1
            if row["duration"] and expected_position(row) >= row["duration"] - END_EPSILON:
                async with s["lock"]:
                    await _advance_locked(room_id, "ended")
                continue
            if cycles % TICK_BROADCAST_EVERY == 0:
                fresh = _playback_row(room_id)
                if fresh and fresh["playing"]:
                    await hub.broadcast_members(room_id, {
                        "type": "music.tick", "roomId": room_id,
                        "videoId": fresh["video_id"], "playing": True,
                        "position": fresh["position"], "anchor": fresh["anchor"],
                        "serverTime": now(), "version": fresh["version"],
                    })
    except asyncio.CancelledError:
        pass
    finally:
        if s["task"] is not None and s["task"] is asyncio.current_task():
            s["task"] = None


def on_room_deleted(room_id: int) -> None:
    s = SESSIONS.pop(room_id, None)
    if s and s["task"]:
        s["task"].cancel()
    db.run("DELETE FROM playback WHERE room_id = ?", room_id)
    db.run("DELETE FROM queue_items WHERE room_id = ?", room_id)
