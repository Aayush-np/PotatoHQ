"""PotatoHQ browser E2E test.

Two separate browser contexts (independent sessions/cookies) drive the real
UI: register, friend each, create/invite/join a room via modals, chat live,
react, verify unread badges, queue real music through the search modal, verify
synchronized player state across both sessions, and join WebRTC voice with
fake microphones.

Requires the server on 127.0.0.1:8420 and `playwright` + chromium installed:
    python tests/browser_e2e.py
"""

import re
import os
import sys
import time
import uuid

from playwright.sync_api import sync_playwright, expect

BASE = os.getenv("POTATO_TEST_BASE", "http://127.0.0.1:8420")
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def register(page, username, display):
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Register").click()
    page.fill("#auth-email", f"{username}@spuds.test")
    page.fill("#auth-username", username)
    page.fill("#auth-display", display)
    page.fill("#auth-password", "spudpass123")
    page.get_by_role("button", name="Join PotatoHQ").click()
    expect(page.locator(".sb-brand")).to_be_visible(timeout=15000)


def main():
    browser_args = [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=browser_args)
        ctx_a = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx_b = browser.new_context(viewport={"width": 1280, "height": 860})
        pa = ctx_a.new_page()
        pb = ctx_b.new_page()

        for pg in (pa, pb):
            pg.on("pageerror", lambda e: print("  [pageerror]", e))
            pg.on("console", lambda m: print("  [console]", m.type, m.text)
                  if m.type == "error" or ("[ws]" in m.text) else None)

        uname_a, uname_b = f"bravo_{uuid.uuid4().hex[:6]}", f"charlie_{uuid.uuid4().hex[:6]}"

        print("== PotatoHQ browser E2E ==")

        # -- registration via the real UI --
        register(pa, uname_a, "Bravo Spud")
        register(pb, uname_b, "Charlie Spud")
        check("both sessions registered + shell rendered", pa.locator(".sb-brand").count() == 1)

        # -- friendship via UI --
        pa.fill("[aria-label='Add a spud by username or email']", uname_b)
        pa.get_by_role("button", name="Add", exact=True).click()
        expect(pa.locator(".toast")).to_contain_text("planted", timeout=8000)
        pb.reload()
        pb.get_by_role("button", name="Accept").first.click()
        expect(pb.locator(".toast")).to_contain_text("spuds now", timeout=8000)
        pa.reload()
        expect(pa.get_by_text("Charlie Spud").first).to_be_visible(timeout=8000)
        check("friend listed on A's home", True)

        # -- create room + invite via modal --
        pa.click("[aria-label='Create a room']")
        pa.fill(".modal input.input", "Browser Bunker")
        pa.locator(".modal .check-row", has_text=uname_b).locator("input").check()
        pa.get_by_role("button", name="Dig the bunker").click()
        expect(pa.locator(".ch-name")).to_contain_text("Browser Bunker", timeout=10000)
        check("room created and opened", True)

        # -- B accepts invite via UI --
        pb.reload()
        pb.get_by_role("button", name="Join", exact=True).first.click()
        expect(pb.locator(".ch-name")).to_contain_text("Browser Bunker", timeout=10000)
        check("invite accepted, room opened for B", True)

        # member strips show each other
        expect(pa.locator(".member-chip", has_text="Charlie Spud")).to_be_visible(timeout=8000)
        check("A sees B in member strip", True)

        # connection banner must be genuinely hidden while connected
        # (regression: display:flex used to override the hidden attribute)
        expect(pa.locator("#conn-banner")).to_be_hidden(timeout=8000)
        check("no connection banner while connected", True)

        # -- live messaging across sessions --
        pa.fill("[aria-label='Message']", "hello from bravo, the browser spud")
        pa.click("[aria-label='Send message']")
        expect(pb.locator(".m-text", has_text="hello from bravo")).to_be_visible(timeout=8000)
        check("message A -> B delivered live", True)

        pb.fill("[aria-label='Message']", "charlie hears you loud and clear")
        pb.click("[aria-label='Send message']")
        expect(pa.locator(".m-text", has_text="charlie hears you")).to_be_visible(timeout=8000)
        check("message B -> A delivered live", True)

        # -- reaction via hover palette --
        msg = pa.locator(".msg", has_text="charlie hears you").last
        msg.hover()
        pa.locator(".msg .m-actions [aria-label='Add a reaction']").last.click()
        pa.locator(".reaction-palette button").first.click()
        expect(pb.locator(".msg", has_text="charlie hears you").last
               .locator(".reaction")).to_be_visible(timeout=8000)
        check("reaction visible to the other session", True)

        # -- reply flow --
        pb.hover(".msg", position={"x": 100, "y": 10})
        pb.locator(".msg .m-actions [aria-label='Reply to this message']").first.click()
        pb.fill("[aria-label='Message']", "replying to myself, very cool")
        pb.click("[aria-label='Send message']")
        expect(pb.locator(".m-reply", has_text="Bravo Spud")).to_be_visible(timeout=8000)
        check("reply preview rendered", True)

        # -- unread badge while A is away --
        pa.goto(BASE + "/#/")
        pb.fill("[aria-label='Message']", "bravo left, badge this")
        pb.click("[aria-label='Send message']")
        expect(pa.locator(".sb-rooms-list .unread-dot")).to_be_visible(timeout=8000)
        check("unread badge appears in A's sidebar", True)
        pa.locator(".sb-rooms-list .sb-row", has_text="Browser Bunker").click()
        expect(pa.locator(".sb-rooms-list .unread-dot")).to_have_count(0, timeout=8000)
        check("badge clears after opening room", True)

        # -- music: discovery through the real search modal (live YouTube Music) --
        pa.click("[aria-label='Search and add music']")
        pa.fill("[aria-label='Search YouTube Music']", "Wonderwall Oasis")
        pa.wait_for_selector(".ms-row .add-btn", timeout=20000)
        atv_first = pa.evaluate("() => window.__potatohq && true") and pa.evaluate(
            "() => document.querySelector('.ms-row .r-title') ? document.querySelector('.ms-row').textContent : ''")
        pa.locator(".ms-row .add-btn").first.click(timeout=20000)
        # the track reaches the authoritative state (title in the bar) even if
        # the headless browser can't play the real embed
        deadline = time.time() + 15
        queued_ok = False
        while time.time() < deadline:
            cur = pa.evaluate("() => (window.__potatohq.player?.state?.current?.title || '') + '|' + window.__potatohq.player?.queue?.map(q => q.title).join(';')")
            if "Wonderwall" in cur:
                queued_ok = True
                break
            time.sleep(0.5)
        check("queued track reached the shared state (both bars)", queued_ok, cur)
        expect(pb.locator(".pb-title")).to_contain_text("Wonderwall", timeout=10000)
        check("B's player bar synced to same track", True)

        # artwork shown, video hidden behind it (no YouTube preview)
        expect(pa.locator(".pb-art img")).to_be_visible(timeout=10000)
        check("album artwork shown instead of video preview", True)
        no_preview = pa.evaluate("""() => {
          const host = document.querySelector('.pb-yt-host iframe');
          if (!host) return 'no-iframe';
          const r = host.getBoundingClientRect();
          const art = document.querySelector('.pb-art img').getBoundingClientRect();
          return (r.width <= art.width + 2 && r.height <= art.height + 2) ? 'covered' : 'exposed';
        }""")
        check("video never exposed (artwork covers the embed)", no_preview != "exposed", no_preview)

        # music volume adjustable + persisted
        pa.locator("[aria-label='Music volume']").fill("35")
        vol = pa.evaluate("() => parseInt(localStorage.getItem('potato-volume'), 10)")
        check("music volume adjustable + persisted", vol == 35, vol)
        pa.keyboard.press("Escape")  # close the search modal

        # -- deterministic shared-playback sync through the real player bar --
        # Headless Chromium can't reliably play real YouTube embeds, so this
        # section drives the sync protocol directly (add / ended reports) with
        # fake tracks while asserting on the real UI both sessions render.
        for pg in (pa, pb):
            pg.evaluate("() => { window.__potatohq.player.suppressEmbedErrors = true; }")
        room_id = pa.evaluate("() => window.__potatohq.store.channel.id")
        F1 = {"videoId": "aaaaaaaaaaa", "title": "Sync Test One", "artist": "The E2E Spuds", "duration": 5.0, "artwork": None}
        F2 = {"videoId": "bbbbbbbbbbb", "title": "Sync Test Two", "artist": "The E2E Spuds", "duration": 5.0, "artwork": None}
        pa.evaluate("""([rid, t1, t2]) => window.__potatohq.send({type:'music.control', roomId: rid,
            action:'add', params:{tracks:[t1, t2]}})""", [room_id, F1, F2])
        # skip past the real (headless-unplayable) track to the fake ones
        pa.evaluate("(rid) => window.__potatohq.send({type:'music.control', roomId: rid, action:'skip'})", room_id)
        expect(pa.locator(".pb-title")).to_contain_text("Sync Test One", timeout=10000)
        expect(pb.locator(".pb-title")).to_contain_text("Sync Test One", timeout=10000)
        check("add on A renders on both bars", True)

        pa.click("[aria-label='Toggle the queue panel']")
        expect(pa.locator("#queue-panel .q-title", has_text="Sync Test Two")).to_be_visible(timeout=8000)
        check("queue panel shows the upcoming track", True)

        # B ends the track -> server advances to the queued one -> A follows
        pb.evaluate("""([rid, vid]) => window.__potatohq.send({type:'music.ended', roomId: rid,
            videoId: vid, duration: 5})""", [room_id, "aaaaaaaaaaa"])
        expect(pa.locator(".pb-title")).to_contain_text("Sync Test Two", timeout=10000)
        expect(pb.locator(".pb-title")).to_contain_text("Sync Test Two", timeout=10000)
        check("track ended on B advances the room on A", True)
        pa.click("[aria-label='Toggle the queue panel']")  # close it again
        expect(pa.locator("#queue-panel")).to_be_hidden(timeout=5000)
        check("queue panel visually closes (hidden attr respected)", True)

        # skip on A -> B follows (authoritative state, identical on both)
        pa.click("[aria-label='Skip to next track']")
        expect(pb.locator(".pb-title.idle")).to_be_visible(timeout=20000)
        expect(pa.locator(".pb-title.idle")).to_be_visible(timeout=8000)
        check("skip on A syncs B (both idle together)", True)

        # -- voice chat with fake microphones --
        pa.get_by_role("button", name="Join voice").click()
        expect(pa.get_by_text("Voice spud-connected")).to_be_visible(timeout=15000)
        check("A joined voice (fake mic)", True)
        pb.get_by_role("button", name="Join voice").click()
        expect(pb.get_by_text("Voice spud-connected")).to_be_visible(timeout=15000)
        check("B joined voice (fake mic)", True)

        # roster shows both participants in both sessions
        expect(pa.locator(".vd-peer", has_text="Charlie Spud")).to_be_visible(timeout=10000)
        expect(pb.locator(".vd-peer", has_text="Bravo Spud")).to_be_visible(timeout=10000)
        check("voice roster shows both spuds", True)

        # peer connections actually form (WebRTC over loopback)
        def peer_states(pg):
            return pg.evaluate("""() => {
                const v = window.__potatohq.voice;
                const out = [];
                for (const [id, peer] of v.peers) out.push(peer.pc.connectionState);
                return out;
            }""")
        deadline = time.time() + 30
        ok = False
        while time.time() < deadline:
            sa, sb = peer_states(pa), peer_states(pb)
            if sa and sb and all(s == "connected" for s in sa + sb):
                ok = True
                break
            time.sleep(1.0)
        check("WebRTC peer connections established", ok, f"A={peer_states(pa)} B={peer_states(pb)}")

        # mute toggle propagates roster state
        pa.get_by_role("button", name="Mute microphone").click()
        expect(pb.locator(".vd-peer", has_text="Bravo Spud").locator(".tag", has_text="muted")
               ).to_be_visible(timeout=8000)
        check("mute state visible to the other session", True)
        pa.get_by_role("button", name="Unmute microphone").click()

        # deafen: mutes mic + shows state on both sides
        pa.get_by_role("button", name="Deafen").click()
        expect(pb.locator(".vd-peer", has_text="Bravo Spud").locator(".tag", has_text="deafened")
               ).to_be_visible(timeout=8000)
        a_deaf = pa.evaluate("() => window.__potatohq.voice.deafened && window.__potatohq.voice.muted")
        check("deafen silences everyone and mutes own mic", a_deaf is True)
        pa.get_by_role("button", name="Undeafen").click()
        expect(pb.locator(".vd-peer", has_text="Bravo Spud").locator(".tag", has_text="deafened")
               ).to_have_count(0, timeout=8000)

        # per-peer volume slider exists for the other spud and persists
        peer_vol = pa.locator(".vd-peer", has_text="Charlie Spud").locator("input[type='range']")
        expect(peer_vol).to_be_visible(timeout=5000)
        peer_vol.fill("150")
        b_id = pb.evaluate("() => window.__potatohq.store.me.id")
        stored = pa.evaluate(f"() => parseFloat(localStorage.getItem('potato-vol-{b_id}'))")
        check("per-spud voice volume adjustable + persisted", stored == 1.5, stored)

        # raise hand shows on the other session
        pb.get_by_role("button", name="Raise hand").click()
        expect(pa.locator(".vd-peer", has_text="Charlie Spud").locator(".raised-icon")
               ).to_be_visible(timeout=8000)
        check("raise hand visible to the other session", True)
        pb.get_by_role("button", name="Lower hand").click()

        # PTT toggle + audio device settings present
        pa.get_by_role("button", name="Toggle push to talk").click()
        ptt_on = pa.evaluate("() => window.__potatohq.voice.pttEnabled === true && localStorage.getItem('potato-audio-ptt') === '1'")
        check("push-to-talk toggle persists", ptt_on is True)
        pa.get_by_role("button", name="Toggle push to talk").click()

        pa.click("[aria-label='Profile and settings']")
        expect(pa.get_by_text("Audio & devices")).to_be_visible(timeout=8000)
        check("audio & devices settings section exists", True)
        pa.keyboard.press("Escape")

        # -- presence + activity in sidebar --
        pb.goto(BASE + "/#/")
        expect(pb.locator(".sb-rooms-list .sb-row", has_text="Browser Bunker")
               .locator(".voice-chip")).to_be_visible(timeout=8000)
        check("voice indicator on room row in sidebar", True)
        expect(pb.locator(".sb-user .name")).to_contain_text("Charlie Spud")
        check("user footer shows B", True)

        # -- mobile viewport sanity --
        mob = ctx_a.new_page()
        mob.set_viewport_size({"width": 390, "height": 844})
        mob.goto(BASE + "/#/")
        expect(mob.locator(".menu-btn")).to_be_visible(timeout=10000)
        mob.click("[aria-label='Open sidebar']")
        expect(mob.locator(".sidebar.open")).to_be_visible(timeout=5000)
        check("mobile: sidebar drawer opens via hamburger", True)

        # -- logout --
        pa.reload()
        pa.click("[aria-label='Profile and settings']")
        pa.get_by_role("button", name="Log out").click()
        expect(pa.get_by_role("tab", name="Sign in")).to_be_visible(timeout=10000)
        check("logout returns to auth screen", True)

        browser.close()

    print(f"\n== browser E2E: {PASS} passed, {FAIL} failed ==")
    return FAIL == 0


if __name__ == "__main__":
    ok = False
    try:
        ok = main()
    except Exception:
        import traceback
        traceback.print_exc()
    sys.exit(0 if ok else 1)
