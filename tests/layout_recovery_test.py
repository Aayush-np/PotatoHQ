"""Layout + reconnect recovery test (self-managed server on port 8421).

1. Flood a room with 60 messages -> the player bar must stay inside the
   viewport (the old flex/grid bug pushed it off-screen into the void).
2. Kill the server under the live page -> banner appears and says the HQ is
   unreachable; restart the server -> banner clears automatically and chat
   works again.

The user's own server on 8420 is never touched.
"""
import os
import subprocess
import time
import uuid

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8421"
PORT = 8421
CWD = r"D:\PotatoHQ"


def start_server():
    env = {**os.environ, "POTATO_PORT": str(PORT), "POTATO_HOST": "0.0.0.0",
           "POTATO_WS_DEBUG": "1"}
    return subprocess.Popen(
        ["python", "run.py"], cwd=CWD, env=env,
        stdout=open("tests/test_server.log", "ab"),
        stderr=subprocess.STDOUT,
    )


def kill_server(proc):
    proc.kill()
    proc.wait(timeout=10)


def register(page, name):
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Register").click()
    page.fill("#auth-email", f"{name}@spuds.test")
    page.fill("#auth-username", name)
    page.fill("#auth-display", name)
    page.fill("#auth-password", "spudpass123")
    page.get_by_role("button", name="Join PotatoHQ").click()
    page.wait_for_selector(".sb-brand", timeout=20000)


def main():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(("  ok  " if cond else "  FAIL ") + name, detail if not cond else "")
        if not cond:
            ok = False

    server = start_server()
    time.sleep(2.5)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page(viewport={"width": 1280, "height": 800})
            pg.on("pageerror", lambda e: print("  [pageerror]", e))
            name = f"layout_{uuid.uuid4().hex[:6]}"
            register(pg, name)

            rid = pg.evaluate("""async () => {
              const r = await fetch('/api/rooms', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({name:'Flood Bunker'})});
              return (await r.json()).room.id;
            }""")
            pg.evaluate(f"location.hash = '#/room/{rid}'")
            pg.wait_for_selector(".composer", timeout=10000)
            pg.evaluate("""async () => {
              const v = window.__potatohq;
              const rid = v.store.channel.id;
              for (let i = 1; i <= 60; i++) {
                v.send({type:'chat.send', roomId: rid, content: 'flood message number ' + i});
                if (i % 5 === 0) await new Promise(r => setTimeout(r, 60));
              }
            }""")
            pg.wait_for_timeout(1500)

            info = pg.evaluate("""() => {
              const bar = document.querySelector('.player-bar').getBoundingClientRect();
              const msgs = document.querySelector('#msgs');
              return {
                barBottom: Math.round(bar.bottom),
                barTop: Math.round(bar.top),
                viewportH: window.innerHeight,
                msgsScrollable: msgs.scrollHeight > msgs.clientHeight + 4,
                msgsClientH: Math.round(msgs.clientHeight),
              };
            }""")
            check("player bar stays inside the viewport with 60 messages",
                  info["barBottom"] <= info["viewportH"] + 1 and info["barTop"] < info["barBottom"] - 20, info)
            check("message list scrolls internally", info["msgsScrollable"], info)

            pg.evaluate("document.querySelector('#msgs').scrollTop = 0")
            pg.wait_for_timeout(300)
            info2 = pg.evaluate("""() => {
              const bar = document.querySelector('.player-bar').getBoundingClientRect();
              return { barBottom: Math.round(bar.bottom), viewportH: window.innerHeight };
            }""")
            check("player bar visible while scrolled to top of history",
                  info2["barBottom"] <= info2["viewportH"] + 1, info2)

            # ---- reconnect recovery ----
            kill_server(server)
            pg.wait_for_timeout(2500)
            banner_up = pg.locator("#conn-banner").is_visible()
            check("banner appears when the server dies", banner_up)

            # after the health probe ticks (~6s), the banner should explain
            # that the HQ itself is unreachable
            pg.wait_for_timeout(8000)
            unreachable_text = pg.evaluate("() => (document.getElementById('conn-banner-text')?.textContent || '').toLowerCase()")
            check("banner explains the HQ is unreachable", "unreachable" in unreachable_text, unreachable_text)

            server = start_server()
            deadline = time.time() + 45
            recovered = False
            first_send_state = None
            while time.time() < deadline:
                if pg.locator("#conn-banner").is_hidden():
                    if first_send_state is None:
                        first_send_state = pg.evaluate("""() => ({
                          ws: window.__potatohq.wsState(),
                          channelId: window.__potatohq.store.channel?.id ?? null,
                        })""")
                    pg.evaluate("""() => {
                      const v = window.__potatohq;
                      if (!v.store.channel) return;
                      v.send({type:'chat.send', roomId: v.store.channel.id, content: 'back from the void'});
                    }""")
                    pg.wait_for_timeout(800)
                    recovered = pg.evaluate("""() =>
                      document.body.innerText.includes('back from the void')""")
                    if recovered:
                        break
                time.sleep(1)
            check("banner clears automatically + chat works after restart", recovered)
            if first_send_state:
                print("  [first-send state]", first_send_state)
            debug = pg.evaluate("""() => ({
              ws: window.__potatohq.wsState(),
              bannerText: document.getElementById('conn-banner-text')?.textContent,
              bannerHidden: document.getElementById('conn-banner').hidden,
              channelId: window.__potatohq.store.channel?.id ?? null,
              msgCount: document.querySelectorAll('.msg, .msg-system').length,
              log: window.__potatohq.wsLog(),
            })""")
            print("  [debug] channel:", debug["channelId"], "| msgs:", debug["msgCount"],
                  "| bannerHidden:", debug["bannerHidden"])
            for entry in debug["log"]:
                print("  [wslog]", entry)
            # server-side truth: did the chat.send messages land in the DB?
            import sqlite3
            con = sqlite3.connect(r"D:\PotatoHQ\data\potatohq.db")
            try:
                n = con.execute(
                    "SELECT COUNT(*) FROM messages WHERE room_id = ? AND content = 'back from the void'",
                    (rid,)).fetchone()[0]
                print("  [server] 'back from the void' messages in DB:", n)
            finally:
                con.close()
            with open(r"D:\PotatoHQ\tests\test_server.log", "r", errors="replace") as f:
                lines = f.readlines()
            ws_dbg = [l.rstrip()[:130] for l in lines if "ws-debug" in l and "chat.send" in l]
            print(f"  [server] chat.send WS messages received after restart: {len(ws_dbg)}")
            print("  [server log tail]")
            for line in lines[-25:]:
                print("   ", line.rstrip()[:130])

            bar_final = pg.evaluate("""() => {
              const bar = document.querySelector('.player-bar').getBoundingClientRect();
              return { barBottom: Math.round(bar.bottom), viewportH: window.innerHeight };
            }""")
            check("player bar still in viewport after recovery",
                  bar_final["barBottom"] <= bar_final["viewportH"] + 1, bar_final)

            browser.close()
    finally:
        kill_server(server)

    print("RESULT:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
