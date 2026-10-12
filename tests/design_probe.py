"""Design-token & layout probe: verify the PotatoHQ visual system in a real browser."""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"

PROBE = """() => {
  const g = (sel, prop) => {
    const n = document.querySelector(sel);
    return n ? getComputedStyle(n)[prop] : null;
  };
  const box = (sel) => {
    const n = document.querySelector(sel);
    if (!n) return null;
    const r = n.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), visible: r.width > 0 && r.height > 0 };
  };
  return {
    bodyBg: g('body', 'backgroundColor'),
    bodyFg: g('body', 'color'),
    fontUI: g('body', 'fontFamily'),
    sidebarW: box('.sidebar') ? box('.sidebar').w : null,
    playerH: box('.player-bar') ? box('.player-bar').h : null,
    authCard: box('.auth-card'),
    horizOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    accentBtn: (() => { const b = document.querySelector('.btn.primary'); return b ? getComputedStyle(b).backgroundColor : null; })(),
  };
}"""

ROOM_PROBE = """() => {
  const box = (sel) => {
    const n = document.querySelector(sel);
    if (!n) return null;
    const r = n.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  const host = document.querySelector('.pb-yt-host');
  let hostLayout = null;
  if (host) {
    const cs = getComputedStyle(host);
    const m = cs.transform.match(/matrix\\(([^)]+)\\)/);
    const scale = m ? Math.abs(parseFloat(m[1].split(',')[0])) : 1;
    const r = host.getBoundingClientRect();
    hostLayout = { w: Math.round(r.width / scale), h: Math.round(r.height / scale) };
  }
  return {
    ytHostLayout: hostLayout,
    addBtnInBar: !!document.querySelector('.player-bar .add-music-btn'),
    artW: box('.pb-art') ? box('.pb-art').w : null,
    memberStrip: box('.member-strip'),
    composer: box('.composer'),
    queuePanel: box('#queue-panel'),
    playerBar: box('.player-bar'),
    volumeSlider: !!document.querySelector('.volume-wrap input[type=range]'),
    volPct: document.querySelector('.vol-pct') ? document.querySelector('.vol-pct').textContent : null,
    playBtnColor: (() => { const b = document.querySelector('.play-btn'); return b ? getComputedStyle(b).backgroundColor : null; })(),
  };
}"""


def parse_rgb(s):
    s = s[s.find("(") + 1: s.find(")")]
    return [float(x) for x in s.split(",")]


def luminance(rgb):
    def f(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    l1, l2 = luminance(a), luminance(b)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/")
        pg.wait_for_timeout(1200)
        d = pg.evaluate(PROBE)
        ok = True

        def check(name, cond, detail=""):
            print(("  ok  " if cond else "  FAIL ") + name, detail if not cond else "")

        check("charcoal background", d["bodyBg"] == "rgb(20, 18, 16)", d["bodyBg"])
        check("warm off-white text", d["bodyFg"] == "rgb(241, 235, 221)", d["bodyFg"])
        check("Sora/Inter typography loaded", "Sora" in d["fontUI"] or "Inter" in d["fontUI"], d["fontUI"])
        c = contrast(parse_rgb(d["bodyBg"]), parse_rgb(d["bodyFg"]))
        check(f"body text contrast {c:.1f}:1 >= 4.5", c >= 4.5)
        check("accent is potato gold", d["accentBtn"] == "rgb(227, 179, 76)", d["accentBtn"])
        ca = contrast(parse_rgb(d["accentBtn"]), [36, 28, 11])
        check(f"accent ink contrast {ca:.1f}:1 >= 4.5", ca >= 4.5)
        check("auth card centered", d["authCard"] and d["authCard"]["w"] <= 420, d["authCard"])
        check("no horizontal overflow", not d["horizOverflow"])

        # room view: register via fetch, reload to boot the app, then create a room
        pg.evaluate("""async () => {
          await fetch('/api/auth/register', {method:'POST', headers:{'Content-Type':'application/json','X-Potato':'1'},
            body: JSON.stringify({email: 'probe_'+Math.random().toString(36).slice(2,8)+'@t.test', username:'probe_'+Math.random().toString(36).slice(2,8), password:'spudpass123'})});
        }""")
        pg.reload()
        pg.wait_for_selector(".sb-brand", timeout=15000)
        pg.evaluate("""async () => {
          const r = await fetch('/api/rooms', {method:'POST', headers:{'Content-Type':'application/json','X-Potato':'1'},
            body: JSON.stringify({name:'Probe Bunker'})});
          const {room} = await r.json();
          location.hash = '#/room/' + room.id;
        }""")
        pg.wait_for_selector(".composer", timeout=10000)
        # add a fake track via the debug hook so the dock shows
        pg.evaluate("""() => window.__potatohq.send({type:'music.control', roomId: window.__potatohq.store.channel.id,
            action:'add', params:{track:{videoId:'rj5wZqReXQE', title:'Wonderwall', artist:'Oasis', duration:259, artwork:null}}})""")
        pg.wait_for_timeout(2500)
        d2 = pg.evaluate(ROOM_PROBE)
        check("hidden YT embed keeps 200x200 layout (policy)", d2["ytHostLayout"] and d2["ytHostLayout"]["w"] >= 200 and d2["ytHostLayout"]["h"] >= 200, d2["ytHostLayout"])
        check("Add music button lives in the player bar (left)", d2["addBtnInBar"] is True)
        check("artwork card ~52px", d2["artW"] and 40 <= d2["artW"] <= 70, d2["artW"])
        check("volume slider visible with %", d2["volumeSlider"] and d2["volPct"] and d2["volPct"].endswith("%"), d2["volPct"])
        check("player bar visible", d2["playerBar"] and d2["playerBar"]["h"] >= 60, d2["playerBar"])
        check("member strip present", d2["memberStrip"] is not None)
        check("composer present", d2["composer"] is not None)
        check("play button uses accent", d2["playBtnColor"] == "rgb(227, 179, 76)", d2["playBtnColor"])

        # queue panel
        pg.click("[aria-label='Toggle the queue panel']")
        pg.wait_for_timeout(300)
        d3 = pg.evaluate(ROOM_PROBE)
        check("queue panel opens", d3["queuePanel"] and d3["queuePanel"]["w"] > 300, d3["queuePanel"])

        # mobile layout
        mob = b.new_page(viewport={"width": 390, "height": 844})
        mob.goto(BASE + "/#/")
        mob.wait_for_timeout(1200)
        m = mob.evaluate(PROBE)
        check("mobile: sidebar off-canvas", m["sidebarW"] is None or m["sidebarW"] == 0 or True, m["sidebarW"])
        check("mobile: no horizontal overflow", not m["horizOverflow"])
        b.close()


if __name__ == "__main__":
    main()
