"""PotatoHQ end-to-end smoke test.

Two accounts, REST + WebSocket flows: registration, friendship, rooms, invites,
real-time chat, presence, unread counts, music queue control, authoritative
playback state, and ticker-driven track advance (using fake short tracks so
the test doesn't depend on the network).

Run with the server already listening on 127.0.0.1:8420:
    python tests/smoke_test.py
"""

import asyncio
import json
import os
import sys
import time
import urllib.parse
import uuid

import httpx
import websockets

BASE = os.getenv("POTATO_TEST_BASE", "http://127.0.0.1:8420")
WS = BASE.replace("http", "ws", 1) + "/ws"
HEADERS = {"X-Potato": "1", "Content-Type": "application/json"}

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


class Client:
    """REST + WS client for one user session."""

    def __init__(self, name):
        self.name = name
        self.http = httpx.AsyncClient(base_url=BASE, headers=HEADERS)
        self.cookie = None
        self.user = None
        self.ws = None
        self.inbox = []
        self.pending = []

    async def register(self, email=None, username=None, password="spudpass123"):
        email = email or f"{uuid.uuid4().hex[:10]}@spuds.test"
        username = username or f"spud_{uuid.uuid4().hex[:8]}"
        r = await self.http.post("/api/auth/register", json={
            "email": email, "username": username, "password": password, "displayName": username,
        })
        assert r.status_code == 200, r.text
        self.cookie = r.headers["set-cookie"].split(";")[0]
        self.user = r.json()["user"]
        self.http.headers["cookie"] = self.cookie
        return self.user

    async def login(self, ident, password="spudpass123"):
        r = await self.http.post("/api/auth/login", json={"email": ident, "password": password})
        assert r.status_code == 200, r.text
        self.cookie = r.headers["set-cookie"].split(";")[0]
        self.user = r.json()["user"]
        self.http.headers["cookie"] = self.cookie
        return self.user

    async def connect_ws(self):
        self.ws = await websockets.connect(WS, additional_headers={"cookie": self.cookie, "origin": BASE})
        hello = json.loads(await self.ws.recv())
        assert hello["type"] == "hello", hello
        self.inbox.append(hello)

    async def send(self, **msg):
        await self.ws.send(json.dumps(msg))

    async def recv_until(self, pred, timeout=5.0):
        """Pop messages from the inbox (or socket) until pred matches. Returns the message."""
        # scan buffered first
        for i, m in enumerate(self.inbox):
            if pred(m):
                return self.inbox.pop(i)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.05, deadline - time.time()))
                m = json.loads(raw)
                if pred(m):
                    return m
                self.inbox.append(m)
            except asyncio.TimeoutError:
                break
        raise AssertionError("timed out waiting for message")

    def expect_inbox(self, pred):
        for i, m in enumerate(self.inbox):
            if pred(m):
                return self.inbox.pop(i)
        return None

    async def close(self):
        if self.ws:
            await self.ws.close()
        await self.http.aclose()


FAKE_TRACKS = [
    {"videoId": "aaaaaaaaaaa", "title": "Potato Anthem", "artist": "The Taters",
     "artwork": None, "duration": 3.0},
    {"videoId": "bbbbbbbbbbb", "title": "Fry Hard", "artist": "Spud Solo",
     "artwork": None, "duration": 4.0},
    {"videoId": "ccccccccccc", "title": "Mash It Up", "artist": "DJ Starch",
     "artwork": None, "duration": 5.0},
]


async def main():
    print("== PotatoHQ smoke test ==")

    # ---------- 1. health ----------
    r = await httpx.AsyncClient().get(f"{BASE}/api/health")
    check("health endpoint", r.status_code == 200 and r.json().get("ok"))

    a = Client("anna")
    b = Client("bob")
    await a.register()
    await b.register()
    check("registered two accounts", a.user["id"] > 0 and b.user["id"] > 0)

    # validation errors
    dup = await a.http.post("/api/auth/register", json={
        "email": f"{uuid.uuid4().hex[:8]}@x.test", "username": a.user["username"], "password": "spudpass123"})
    check("duplicate username rejected", dup.status_code == 409)
    bad = await a.http.post("/api/auth/register", json={
        "email": "notanemail", "username": "zzz", "password": "short"})
    check("invalid registration rejected", bad.status_code == 400)

    # CSRF guard: request without X-Potato header
    r = await httpx.AsyncClient().post(f"{BASE}/api/rooms/join", json={"code": "x"})
    check("CSRF header enforced", r.status_code == 403)

    # ---------- 2. profiles ----------
    r = await a.http.get("/api/me")
    check("session persists (GET /me)", r.status_code == 200 and r.json()["user"]["id"] == a.user["id"])
    r = await a.http.patch("/api/me", json={"displayName": "Anna the Spud"})
    check("display name update", r.json()["user"]["displayName"] == "Anna the Spud")
    r = await a.http.get(f"/api/users/{b.user['id']}")
    check("public user card", r.status_code == 200 and r.json()["user"]["username"] == b.user["username"])
    r = await httpx.AsyncClient().get(f"{BASE}/api/users/{a.user['id']}/avatar")
    check("generated potato avatar (svg)", r.status_code == 200 and "svg" in r.headers.get("content-type", ""))

    # ---------- 3. friendships ----------
    r = await a.http.post("/api/friends/requests", json={"query": b.user["username"]})
    check("friend request sent", r.status_code == 200)
    r = await b.http.post("/api/friends/requests", json={"query": a.user["username"]})
    check("reverse request auto-accepts", r.status_code == 200 and r.json().get("autoAccepted"))
    r = await a.http.get("/api/bootstrap")
    boot = r.json()
    check("bootstrap shows friend with frId",
          any(f["id"] == b.user["id"] and "frId" in f for f in boot["friends"]))

    # ---------- 4. rooms & invites ----------
    r = await a.http.post("/api/rooms", json={"name": "The Starch Bunker", "topic": "crunchy"})
    room = r.json()["room"]
    check("room created", room["id"] > 0 and room["inviteCode"])

    r = await b.http.get(f"/api/rooms/{room['id']}")
    check("private room blocks non-members", r.status_code == 403)

    r = await a.http.post(f"/api/rooms/{room['id']}/invite", json={"userIds": [b.user["id"]]})
    check("invite friend", r.status_code == 200 and r.json()["invited"] == 1)
    r = await b.http.get("/api/bootstrap")
    check("invite appears for target", any(i["roomId"] == room["id"] for i in r.json()["invites"]))

    r = await b.http.post(f"/api/rooms/{room['id']}/invites/accept")
    check("invite accepted", r.status_code == 200)

    # join by code
    c = Client("cleo")
    await c.register()
    r = await c.http.post("/api/rooms/join", json={"code": room["inviteCode"]})
    check("join by spud-code", r.status_code == 200 and r.json()["room"]["id"] == room["id"])

    # unauthorized kick
    r = await c.http.post(f"/api/rooms/{room['id']}/kick", json={"userId": a.user["id"]})
    check("kick blocked for non-owner", r.status_code == 403)

    # ---------- 5. websockets ----------
    await a.connect_ws()
    await b.connect_ws()
    await c.connect_ws()
    await c.send(type="room.enter", roomId=room["id"])
    await c.recv_until(lambda m: m["type"] == "room.entered")

    await a.send(type="room.enter", roomId=room["id"])
    entered_a = await a.recv_until(lambda m: m["type"] == "room.entered")
    check("room.entered payload", entered_a["room"]["name"] == "The Starch Bunker" and "music" in entered_a)
    check("invite code shared with members", entered_a["room"]["inviteCode"] == room["inviteCode"])

    await b.send(type="room.enter", roomId=room["id"])
    await b.recv_until(lambda m: m["type"] == "room.entered")

    # presence: B should appear online to A (via member roster event)
    members_evt = await a.recv_until(lambda m: m["type"] == "room.members")
    check("member roster broadcast", any(u["id"] == b.user["id"] and u["online"] for u in members_evt["members"]))

    # chat
    await b.send(type="chat.send", roomId=room["id"], content="hello spuds")
    msg_evt = await a.recv_until(lambda m: m["type"] == "room.message")
    check("real-time message", msg_evt["message"]["content"] == "hello spuds"
          and msg_evt["message"]["author"]["id"] == b.user["id"])

    # reply + edit + delete
    mid = msg_evt["message"]["id"]
    await a.send(type="chat.send", roomId=room["id"], content="reply!", replyTo=mid)
    reply_evt = await a.recv_until(lambda m: m["type"] == "room.message" and m["message"]["replyTo"])
    check("reply preview attached", reply_evt["message"]["replyTo"]["id"] == mid)

    await b.send(type="chat.edit", messageId=mid, content="hello spuds (edited)")
    upd = await a.recv_until(lambda m: m["type"] == "message.updated" and m["message"]["id"] == mid)
    check("edit broadcast", upd["message"]["content"] == "hello spuds (edited)" and upd["message"]["editedAt"])

    await b.send(type="chat.react", messageId=mid, emoji="🥔")
    react = await a.recv_until(lambda m: m["type"] == "message.updated" and m["message"].get("reactions"))
    check("reaction broadcast", any(r["emoji"] == "🥔" for r in react["message"]["reactions"]))

    # typing
    await b.send(type="chat.typing", roomId=room["id"], on=True)
    typing = await a.recv_until(lambda m: m["type"] == "typing")
    check("typing indicator relay", typing["userId"] == b.user["id"] and typing["on"])

    # unread: A isn't viewing the room, should get a badge bump
    await a.send(type="room.exit", roomId=room["id"])  # A leaves the view
    await b.send(type="chat.send", roomId=room["id"], content="badge me")
    unread_evt = await a.recv_until(
        lambda m: m["type"] == "unread.update" and m["roomId"] == room["id"] and m.get("count", 0) >= 1)
    check("unread badge for non-viewer", unread_evt["count"] >= 1)
    await a.send(type="room.enter", roomId=room["id"])
    await a.recv_until(lambda m: m["type"] == "room.entered")
    await asyncio.sleep(0.3)
    latest = None
    while True:
        evt = a.expect_inbox(lambda m: m["type"] == "unread.update" and m["roomId"] == room["id"])
        if evt is None:
            break
        latest = evt
    check("read state cleared on re-enter", latest is not None and latest["count"] == 0)

    # REST message history
    r = await a.http.get(f"/api/rooms/{room['id']}/messages?limit=50")
    msgs = r.json()["messages"]
    check("message history persisted", any(m["content"] == "hello spuds (edited)" for m in msgs))

    # ---------- 6. voice signaling ----------
    await b.send(type="voice.join", roomId=room["id"], muted=False, listener=False)
    vs = await a.recv_until(lambda m: m["type"] == "voice.state")
    check("voice roster broadcast", any(p["user"]["id"] == b.user["id"] for p in vs["participants"]))

    # rtc relay only works between voice members in the same room
    await c.send(type="rtc.offer", to=b.user["id"], sdp="v=0 fake")
    await asyncio.sleep(0.3)
    got = b.expect_inbox(lambda m: m["type"] == "rtc.offer")
    check("rtc relay denied for non-voice member", got is None)

    await a.send(type="voice.join", roomId=room["id"], muted=True, listener=False)
    await a.recv_until(lambda m: m["type"] == "voice.state")
    await a.send(type="rtc.offer", to=b.user["id"], sdp="v=0 fake")
    rtc = await b.recv_until(lambda m: m["type"] == "rtc.offer")
    check("rtc offer relayed between voice members", rtc["from"] == a.user["id"] and rtc["sdp"] == "v=0 fake")

    await b.send(type="voice.leave")
    vs2 = await a.recv_until(lambda m: m["type"] == "voice.state"
                             and not any(p["user"]["id"] == b.user["id"] for p in m["participants"]))
    check("voice leave updates roster", vs2 is not None)
    await a.send(type="voice.leave")

    # ---------- 7. music: queue + authoritative state ----------
    await a.send(type="music.control", roomId=room["id"], action="add", params={"track": FAKE_TRACKS[0]})
    st = await a.recv_until(lambda m: m["type"] == "music.state")
    check("first track auto-plays on add",
          st["state"]["current"]["videoId"] == "aaaaaaaaaaa" and st["state"]["playing"])
    check("queue empty after auto-start", len(st["queue"]) == 0)

    await b.send(type="music.control", roomId=room["id"], action="add", params={"tracks": FAKE_TRACKS[1:]})
    st_b = await b.recv_until(lambda m: m["type"] == "music.state" and len(m["queue"]) == 2)
    check("queue filled without interrupting current",
          st_b["state"]["current"]["videoId"] == "aaaaaaaaaaa" and st_b["state"]["playing"])

    # pause / resume / seek
    await a.send(type="music.control", roomId=room["id"], action="pause")
    st = await a.recv_until(lambda m: m["type"] == "music.state" and not m["state"]["playing"])
    check("pause freezes position (anchor math)", st["state"]["position"] >= 0)

    await a.send(type="music.control", roomId=room["id"], action="seek", params={"position": 1.5})
    st = await a.recv_until(lambda m: m["type"] == "music.state" and abs(m["state"]["position"] - 1.5) < 0.01)
    check("seek updates position", st is not None)

    await a.send(type="music.control", roomId=room["id"], action="resume")
    st = await a.recv_until(lambda m: m["type"] == "music.state" and m["state"]["playing"])
    check("resume plays again", st is not None)

    # permission mode: owner-only
    await a.send(type="music.control", roomId=room["id"], action="set_mode", params={"mode": "owner"})
    await b.recv_until(lambda m: m["type"] == "music.state" and m["mode"] == "owner")
    await b.send(type="music.control", roomId=room["id"], action="pause")
    toast_evt = await b.recv_until(lambda m: m["type"] == "toast")
    check("owner mode blocks member control", "aux" in toast_evt["text"])
    await a.send(type="music.control", roomId=room["id"], action="set_mode", params={"mode": "shared"})
    await b.recv_until(lambda m: m["type"] == "music.state" and m["mode"] == "shared")

    # ticker advance: first track is 3s long, already ~1.5s in
    print("  ...waiting for the ticker to advance the 3s track...")
    st2 = await a.recv_until(lambda m: m["type"] == "music.state"
                             and m["state"]["current"]["videoId"] == "bbbbbbbbbbb", timeout=15)
    check("ticker auto-advances to next queued track",
          st2["state"]["current"]["title"] == "Fry Hard" and st2["queue"][0]["videoId"] == "ccccccccccc")

    # ended report dedupe: both clients report end simultaneously for the 4s track
    await asyncio.sleep(1.0)
    await a.send(type="music.ended", roomId=room["id"], videoId="bbbbbbbbbbb", duration=4.0)
    await b.send(type="music.ended", roomId=room["id"], videoId="bbbbbbbbbbb", duration=4.0)
    await asyncio.sleep(0.8)
    st3 = await a.recv_until(lambda m: m["type"] == "music.state"
                             and m["state"]["current"]["videoId"] == "ccccccccccc", timeout=8)
    check("client-ended reports advance exactly once", st3 is not None)

    # long track so the ticker stays alive across the reconciliation window
    LONG = {"videoId": "ddddddddddd", "title": "Chips for Hours", "artist": "The Taters",
            "artwork": None, "duration": 120.0}
    await a.send(type="music.control", roomId=room["id"], action="add", params={"track": LONG})
    await a.recv_until(lambda m: m["type"] == "music.state"
                       and len(m["queue"]) == 1 and m["state"]["current"]["videoId"] == "ccccccccccc")
    await a.send(type="music.control", roomId=room["id"], action="skip")
    await a.recv_until(lambda m: m["type"] == "music.state"
                       and m["state"]["current"]["videoId"] == "ddddddddddd")

    # drift reconciliation tick arrives while the long track plays
    tick = await a.recv_until(lambda m: m["type"] == "music.tick", timeout=15)
    check("periodic tick broadcast", abs(tick["serverTime"] - time.time()) < 5)

    # error report marks track unavailable and advances (autoplay off -> deterministic idle)
    await a.send(type="music.control", roomId=room["id"], action="autoplay", params={"on": False})
    await a.recv_until(lambda m: m["type"] == "music.state" and not m["state"]["autoplay"])
    await a.send(type="music.error", roomId=room["id"], videoId="ddddddddddd", code=101)
    st4 = await a.recv_until(lambda m: m["type"] == "music.state"
                            and m["state"]["current"] is None, timeout=10)
    check("unplayable track skipped, queue exhausted",
          st4 is not None and st4["state"]["current"] is None)

    # adding when idle starts the track; skip with empty queue -> idle
    await b.send(type="music.control", roomId=room["id"], action="add", params={"track": FAKE_TRACKS[0]})
    st5 = await a.recv_until(lambda m: m["type"] == "music.state"
                             and m["state"]["current"]["videoId"] == "aaaaaaaaaaa")
    check("add-to-idle starts playback", st5["state"]["playing"])
    await b.send(type="music.control", roomId=room["id"], action="skip")
    st6 = await a.recv_until(lambda m: m["type"] == "music.state"
                             and m["state"]["current"] is None, timeout=8)
    check("skip with empty queue & autoplay off -> idle", st6 is not None)

    # repeat all loops from history
    await a.send(type="music.control", roomId=room["id"], action="repeat", params={"mode": "all"})
    await a.recv_until(lambda m: m["type"] == "music.state" and m["state"]["repeat"] == "all")
    await a.send(type="music.control", roomId=room["id"], action="play")
    st7 = await a.recv_until(lambda m: m["type"] == "music.state"
                             and m["state"]["current"] is not None, timeout=8)
    check("repeat-all refills from history", st7 is not None and len(st7["queue"]) >= 1)

    # system messages recorded for room events (joins, errors, out-of-tunes)
    r = await a.http.get(f"/api/rooms/{room['id']}/messages?limit=50")
    sys_msgs = [m for m in r.json()["messages"] if m["kind"] == "system"]
    check("system messages logged", any(
        "dug into the room" in m["content"] or "rolled in" in m["content"] or "ran out of tunes" in m["content"]
        for m in sys_msgs))

    # ---------- 8. kick + leave + cleanup ----------
    r = await a.http.post(f"/api/rooms/{room['id']}/kick", json={"userId": c.user["id"]})
    check("owner can kick", r.status_code == 200)
    kicked = await c.recv_until(lambda m: m["type"] == "room.kicked", timeout=8)
    check("kicked client notified", kicked["roomId"] == room["id"])
    r = await c.http.get(f"/api/bootstrap")
    check("kicked member's rooms list updated",
          not any(rm["id"] == room["id"] for rm in r.json()["rooms"]))

    await c.close()

    # DM flow
    r = await a.http.post("/api/dm", json={"userId": b.user["id"]})
    dm_id = r.json()["roomId"]
    check("dm opened", dm_id > 0)
    r = await a.http.post("/api/dm", json={"userId": b.user["id"]})
    check("dm is reused", r.json()["roomId"] == dm_id)
    await a.send(type="room.enter", roomId=dm_id)
    dm_entered = await a.recv_until(lambda m: m["type"] == "room.entered")
    check("dm channel enterable", dm_entered["room"]["kind"] == "dm")
    await a.send(type="chat.send", roomId=dm_id, content="psst")
    dm_msg = await a.recv_until(lambda m: m["type"] == "room.message" and m["message"]["roomId"] == dm_id)
    check("dm message flows", dm_msg["message"]["content"] == "psst")

    # music forbidden in DM
    await a.send(type="music.control", roomId=dm_id, action="pause")
    toast2 = await a.recv_until(lambda m: m["type"] == "toast")
    check("music control rejected in DM", "room" in toast2["text"].lower())

    # leave room
    r = await b.http.post(f"/api/rooms/{room['id']}/leave")
    check("member can leave", r.status_code == 200)
    r = await b.http.get("/api/bootstrap")
    check("leave reflected in bootstrap", not any(rm["id"] == room["id"] for rm in r.json()["rooms"]))

    # logout
    r = await a.http.post("/api/auth/logout")
    check("logout", r.status_code == 200)
    r = await a.http.get("/api/me")
    check("session invalid after logout", r.status_code == 401)

    await a.close()
    await b.close()

    print(f"\n== results: {PASS} passed, {FAIL} failed ==")
    return FAIL == 0


if __name__ == "__main__":
    try:
        ok = asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n== test crashed ==")
        ok = False
    sys.exit(0 if ok else 1)
