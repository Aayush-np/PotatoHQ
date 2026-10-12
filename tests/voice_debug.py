"""Focused voice debug: two contexts join voice; inspect peer setup step by step."""
import time
import uuid

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"


def register(page, name):
    name = f"{name}_{uuid.uuid4().hex[:6]}"
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Register").click()
    page.fill("#auth-email", f"{name}@spuds.test")
    page.fill("#auth-username", name)
    page.fill("#auth-display", name)
    page.fill("#auth-password", "spudpass123")
    page.get_by_role("button", name="Join PotatoHQ").click()
    page.wait_for_selector(".sb-brand", timeout=15000)
    return name


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
        ])
        a, c = b.new_context(), b.new_context()
        pa, pb = a.new_page(), c.new_page()
        for pg in (pa, pb):
            pg.on("pageerror", lambda e: print("  [pageerror]", e))
        name_a = register(pa, "voice_a")
        name_b = register(pb, "voice_b")
        # friend + room via API for speed
        pa.evaluate("""async (other) => {
          const r = await fetch('/api/friends/requests', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({query: other})});
          const room = await (await fetch('/api/rooms', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({name:'Voice Lab'})})).json();
        }""", name_b)
        pb.reload()
        pb.get_by_role("button", name="Accept").first.click()
        pb.wait_for_timeout(800)
        pa.evaluate("""async () => {
          const boot = await (await fetch('/api/bootstrap')).json();
          const friendId = boot.friends[0].id;
          await fetch('/api/rooms/' + window.__potatohq.store.rooms[0].id + '/invite', {method:'POST',headers:{'Content-Type':'application/json','X-Potato':'1'},body:JSON.stringify({userIds:[friendId]})});
          location.hash = '#/room/' + window.__potatohq.store.rooms[0].id;
        }""")
        pa.wait_for_selector(".composer", timeout=10000)
        pb.reload()
        pb.get_by_role("button", name="Join", exact=True).first.click()
        pb.wait_for_selector(".composer", timeout=10000)

        print("A joining voice…")
        # instrument ICE candidate flow before joining
        ice_patch = """() => {
          window.__iceStats = { sent: 0, recv: 0, errors: [], gathering: [] };
          const origSend = window.__potatohq.send;
          window.__potatohq.send = (m) => {
            if (m && m.type === 'rtc.ice') window.__iceStats.sent++;
            return origSend(m);
          };
          const origAdd = RTCPeerConnection.prototype.addIceCandidate;
          RTCPeerConnection.prototype.addIceCandidate = async function (c) {
            try { await origAdd.call(this, c); window.__iceStats.recv++; }
            catch (e) { window.__iceStats.errors.push(String(e).slice(0, 120)); }
          };
          const engine = window.__potatohq.voice;
          const origCreate = engine.createPeer.bind(engine);
          engine.createPeer = (id) => {
            const pc = origCreate(id);
            pc.addEventListener('icegatheringstatechange', () => window.__iceStats.gathering.push(pc.iceGatheringState));
            return pc;
          };
        }"""
        pa.evaluate(ice_patch)
        pb.evaluate(ice_patch)
        pa.get_by_role("button", name="Join voice").click()
        pa.wait_for_timeout(3000)
        info = pa.evaluate("""() => {
          const v = window.__potatohq.voice;
          return {
            ownId: window.__potatohq.store.me.id,
            roomId: v.roomId, status: v.status,
            ice: v.iceServers,
            participants: v.participants.map(p => [p.user.id, p.user.displayName]),
            peers: [...v.peers.entries()].map(([id, pr]) => [id, pr.pc.signalingState, pr.pc.connectionState]),
          };
        }""")
        print("A after join:", info)

        print("B joining voice…")
        pb.get_by_role("button", name="Join voice").click()
        pb.wait_for_timeout(2000)
        for who, pg in (("A", pa), ("B", pb)):
            info = pg.evaluate("""() => {
              const v = window.__potatohq.voice;
              return {
                ownId: window.__potatohq.store.me.id,
                participants: v.participants.map(p => p.user.id),
                peers: [...v.peers.entries()].map(([id, pr]) => [id, pr.pc.signalingState, pr.pc.connectionState]),
              };
            }""")
            print(who, "after both joined:", info)

        for _ in range(15):
            time.sleep(1)
            sa = pa.evaluate("[...window.__potatohq.voice.peers.values()].map(p => p.pc.connectionState)")
            sb = pb.evaluate("[...window.__potatohq.voice.peers.values()].map(p => p.pc.connectionState)")
            print("t+", sa, sb)
            if sa and sb and all(s == "connected" for s in sa + sb):
                print("CONNECTED!")
                break
        for who, pg in (("A", pa), ("B", pb)):
            stats = pg.evaluate("() => window.__iceStats")
            detail = pg.evaluate("""() => {
              const v = window.__potatohq.voice;
              const pcs = [...v.peers.values()];
              return pcs.map(p => ({
                gathering: p.pc.iceGatheringState,
                localHasCandidate: /candidate/.test(p.pc.localDescription?.sdp || ''),
                remoteHasCandidate: /candidate/.test(p.pc.remoteDescription?.sdp || ''),
              }));
            }""")
            print(who, "ice:", stats, "pc:", detail)
        b.close()


if __name__ == "__main__":
    main()
