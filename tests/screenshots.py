"""Capture fresh PotatoHQ screenshots for the GitHub README.

Four friends — Aayush, Aakash, Aalok, Dikshant — register, friend up, hang out
in a room with chat, voice, and a live shared queue of Nepali tracks
(Sarangi, Bardali). Runs HEADED so the YouTube embed genuinely plays — the
screenshots show real album art, progress and the fixed mobile layout.

Run with a server on POTATO_TEST_BASE (default http://127.0.0.1:8421).
"""
import os
import time
import uuid

from playwright.sync_api import sync_playwright

BASE = os.getenv("POTATO_TEST_BASE", "http://127.0.0.1:8421")
OUT = "docs/screenshots/"
ARGS = [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]

FRIENDS = [
    {"name": "Aayush", "tagline": "host"},
    {"name": "Aakash", "tagline": None},
    {"name": "Aalok", "tagline": None},
    {"name": "Dikshant", "tagline": None},
]

# queries whose first result is a clean, embeddable YouTube Music audio track
SEARCHES = ["sarangi", "bardali", "dhanyabad"]

CHAT = [
    (0, "yo who put on sarangi on loop 😭"),
    (1, "bro it's the bunker anthem at this point"),
    (2, "and yet… nobody is skipping it"),
    (0, "the bunker has spoken 🥔"),
    (3, "wait wait i love this part"),
    (3, "someone queue the next one, my turn to DJ"),
    (1, "adding bardali, don't @ me"),
    (2, "aayush your mic is so loud lol"),
    (0, "that's what the volume slider is for 🥔"),
]


def register(page, f):
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Register").click()
    page.fill("#auth-email", f"{f['name'].lower()}_{uuid.uuid4().hex[:6]}@spuds.test")
    page.fill("#auth-username", f"{f['name'].lower()}_{uuid.uuid4().hex[:6]}")
    page.fill("#auth-display", f["name"])
    page.fill("#auth-password", "spudpass123")
    page.get_by_role("button", name="Join PotatoHQ").click()
    page.wait_for_selector(".sb-brand", timeout=20000)


def main():
    os.makedirs(os.path.join(os.getcwd(), OUT.replace("/", "\\")), exist_ok=True)
    with sync_playwright() as p:
        # HEADED: the YouTube embed actually plays, so artwork/progress in the
        # shots are the real thing (not a headless stub)
        browser = p.chromium.launch(args=ARGS, headless=False)
        ctxs = [browser.new_context(viewport={"width": 1440, "height": 900} if i == 0 else {"width": 1280, "height": 820}) for i in range(4)]
        pages = [c.new_page() for c in ctxs]

        # --- 1. the login screen ---
        pages[0].goto(BASE + "/")
        pages[0].wait_for_timeout(1200)
        pages[0].screenshot(path=OUT + "1-signin.png")

        # --- register everyone ---
        for pg, f in zip(pages, FRIENDS):
            register(pg, f)
        host = pages[0]

        # --- Aayush friends the other three, they accept ---
        friend_usernames = [pg.evaluate("() => window.__potatohq.store.me.username") for pg in pages[1:]]
        for uname in friend_usernames:
            host.evaluate("""async (q) => {
              await fetch('/api/friends/requests', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({query:q})});
            }""", uname)
        for pg in pages[1:]:
            pg.reload()
            pg.get_by_role("button", name="Accept").first.click()
            pg.wait_for_timeout(400)

        # --- Aayush creates the bunker and invites everyone ---
        host.reload()
        host.wait_for_timeout(500)
        host.click("[aria-label='Create a room']")
        host.fill(".modal input.input", "The Starch Bunker")
        host.fill(".modal .input >> nth=1", "late-night tunes and general nonsense")
        for uname in friend_usernames:
            host.locator(".modal .check-row", has_text=uname).locator("input").check()
        host.get_by_role("button", name="Dig the bunker").click()
        host.wait_for_selector(".ch-name", timeout=15000)
        for pg in pages[1:]:
            pg.reload()
            pg.get_by_role("button", name="Join", exact=True).first.click()
            pg.wait_for_selector(".ch-name", timeout=15000)

        # --- everyone joins voice ---
        for pg in pages:
            pg.get_by_role("button", name="Join voice").click()
            pg.wait_for_timeout(900)
        host.wait_for_timeout(1200)

        # --- the conversation ---
        for who, text in CHAT:
            pages[who].fill("[aria-label='Message']", text)
            pages[who].click("[aria-label='Send message']")
            time.sleep(0.35)
        host.wait_for_timeout(800)

        # --- 2. home with friends online (Aayush's view) ---
        host.goto(BASE + "/#/")
        host.wait_for_timeout(700)
        host.screenshot(path=OUT + "2-home.png")

        # --- music: known-good Nepali tracks, then the real search modal ---
        host.goto(BASE + "/#/room/" + str(host.evaluate("() => window.__potatohq.store.rooms[0].id")))
        host.wait_for_selector(".composer", timeout=10000)
        # YouTube serves bot-detection errors to automation browsers (even
        # headed Playwright Chromium), so every page suppresses embed-failure
        # reports for the shoot — the player bar renders artwork + progress
        # from the authoritative server state, which keeps ticking regardless.
        for pg in pages:
            pg.evaluate("() => { window.__potatohq.player.suppressEmbedErrors = true; }")
        # deterministic queue: Sarangi (Sushant KC) plays now, Bardali and
        # Dhanyabad (Humane Sagar) wait in the queue — ATV tracks that embed fine
        host.evaluate("""() => {
          const v = window.__potatohq;
          v.send({type:'music.control', roomId: v.store.channel.id, action:'add', params:{tracks:[
            {videoId:'RRJEfcdF8vQ', title:'Sarangi', artist:'Sushant KC', duration:245,
             artwork:'https://i.ytimg.com/vi/RRJEfcdF8vQ/hqdefault.jpg'},
            {videoId:'H2xaiUjYbRw', title:'Bardali', artist:'Sushant KC', duration:227,
             artwork:'https://i.ytimg.com/vi/H2xaiUjYbRw/hqdefault.jpg'},
            {videoId:'Tf2HsBAaVOY', title:'Dhanyabad', artist:'Humane Sagar', duration:246,
             artwork:'https://i.ytimg.com/vi/Tf2HsBAaVOY/hqdefault.jpg'},
          ]}});
        }""")
        host.click("[aria-label='Search and add music']")
        host.fill("[aria-label='Search YouTube Music']", "sarangi")
        host.wait_for_selector(".ms-row .add-btn", timeout=25000)
        host.wait_for_timeout(500)
        host.screenshot(path=OUT + "3-music-search.png")
        host.locator(".ms-row .add-btn").nth(0).click()  # a real queue action in the shot
        host.wait_for_timeout(600)
        host.keyboard.press("Escape")
        # let the track genuinely start: artwork + a mid-song progress bar
        host.wait_for_timeout(9000)

        # --- 3. the room: chat + members + voice + live music ---
        host.screenshot(path=OUT + "4-room.png")

        # --- 4. the queue panel ---
        host.click("[aria-label='Toggle the queue panel']")
        host.wait_for_timeout(500)
        host.screenshot(path=OUT + "5-queue.png")

        # --- 5. Aakash's view (multi-device feel) ---
        pages[1].wait_for_timeout(600)
        pages[1].screenshot(path=OUT + "6-friend-view.png")

        # --- 6. mobile ---
        mob = ctxs[0].new_page()
        mob.set_viewport_size({"width": 390, "height": 844})
        mob.goto(BASE + "/")
        mob.wait_for_timeout(1500)
        mob.screenshot(path=OUT + "7-mobile-home.png")
        rid = host.evaluate("() => window.__potatohq.store.rooms[0].id")
        mob.goto(BASE + "/#/room/" + str(rid))
        mob.wait_for_selector(".composer", timeout=10000)
        mob.evaluate("() => { window.__potatohq.player.suppressEmbedErrors = true; }")
        mob.wait_for_timeout(1800)
        mob.screenshot(path=OUT + "8-mobile-room.png")
        mob.click("[aria-label='Open sidebar']")
        mob.wait_for_timeout(500)
        mob.screenshot(path=OUT + "9-mobile-drawer.png")

        browser.close()
        print("screenshots saved to", OUT)


if __name__ == "__main__":
    main()
