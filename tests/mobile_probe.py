"""Mobile layout probe: at 390px, no player-bar element may overlap another,
and the bar must fit the viewport height."""
import os
import uuid

from playwright.sync_api import sync_playwright

BASE = os.getenv("POTATO_TEST_BASE", "http://127.0.0.1:8421")

PROBE = """() => {
  const els = [...document.querySelectorAll('.player-bar .btn-icon, .player-bar .btn, .player-bar input[type=range], .player-bar .pb-now, .player-bar .pb-title, .player-bar .pb-artist, .player-bar .pb-progress, .player-bar .pb-left, .player-bar .pb-side')]
    .filter(e => e.offsetParent !== null && e.getBoundingClientRect().width > 0);
  const rects = els.map(e => {
    const r = e.getBoundingClientRect();
    return { name: (e.className || e.tagName).toString().slice(0, 30), l: r.left, t: r.top, r: r.right, b: r.bottom };
  });
  const overlaps = [];
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j];
      const x = Math.min(a.r, b.r) - Math.max(a.l, b.l);
      const y = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      if (x > 4 && y > 4) {
        // nested-by-design pairs are fine (title inside now, now inside bar)
        const nested = (a.l <= b.l + 2 && a.r >= b.r - 2 && a.t <= b.t + 2 && a.b >= b.b - 2) ||
                       (b.l <= a.l + 2 && b.r >= a.r - 2 && b.t <= a.t + 2 && b.b >= a.b - 2);
        if (!nested) overlaps.push(a.name + ' × ' + b.name);
      }
    }
  }
  const bar = document.querySelector('.player-bar').getBoundingClientRect();
  return { overlaps, barBottom: Math.round(bar.bottom), barH: Math.round(bar.height), vh: window.innerHeight };
}"""


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844})
        pg.goto(BASE + "/")
        pg.get_by_role("tab", name="Register").click()
        pg.fill("#auth-email", f"mob_{uuid.uuid4().hex[:6]}@spuds.test")
        pg.fill("#auth-username", f"mob_{uuid.uuid4().hex[:6]}")
        pg.fill("#auth-display", "Aayush")
        pg.fill("#auth-password", "spudpass123")
        pg.get_by_role("button", name="Join PotatoHQ").click()
        pg.wait_for_selector(".sb-brand", timeout=15000)

        rid = pg.evaluate("""async () => {
          const r = await fetch('/api/rooms', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({name:'The Starch Bunker'})});
          return (await r.json()).room.id;
        }""")
        pg.evaluate(f"location.hash = '#/room/{rid}'")
        pg.wait_for_selector(".composer", timeout=10000)

        # idle bar
        info = pg.evaluate(PROBE)
        print("idle bar:", info)
        assert not info["overlaps"], f"OVERLAPS (idle): {info['overlaps']}"
        assert info["barBottom"] <= info["vh"] + 1, "bar exceeds viewport"

        # with a live track playing (server state; artwork shown)
        pg.evaluate("""() => { window.__potatohq.player.suppressEmbedErrors = true; }""")
        pg.evaluate("""() => {
          const v = window.__potatohq;
          v.send({type:'music.control', roomId: v.store.channel.id, action:'add',
            params:{tracks:[
              {videoId:'RRJEfcdF8vQ', title:'Sarangi', artist:'Sushant KC', duration:245, artwork:null},
              {videoId:'H2xaiUjYbRw', title:'Bardali', artist:'Sushant KC', duration:227, artwork:null},
            ]}});
        }""")
        pg.wait_for_timeout(2500)
        info2 = pg.evaluate(PROBE)
        print("playing bar:", info2)
        assert not info2["overlaps"], f"OVERLAPS (playing): {info2['overlaps']}"
        assert info2["barBottom"] <= info2["vh"] + 1, "bar exceeds viewport"

        # queue panel must not collide with the bar
        pg.click("[aria-label='Toggle the queue panel']")
        pg.wait_for_timeout(400)
        qp = pg.evaluate("""() => {
          const panel = document.querySelector('#queue-panel').getBoundingClientRect();
          const bar = document.querySelector('.player-bar').getBoundingClientRect();
          return { panelBottom: Math.round(panel.bottom), barTop: Math.round(bar.top),
                   overlap: panel.bottom > bar.top + 2 };
        }""")
        print("queue panel:", qp)
        assert not qp["overlap"], "queue panel overlaps player bar"

        print("MOBILE LAYOUT OK")
        b.close()


if __name__ == "__main__":
    main()
