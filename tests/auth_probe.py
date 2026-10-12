"""Quick auth-screen probe."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    msgs = []
    pg.on("console", lambda m: msgs.append(m.type + ": " + m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: msgs.append("PAGEERROR: " + str(e)))
    pg.goto("http://127.0.0.1:8420/")
    pg.wait_for_timeout(1500)
    pg.get_by_role("tab", name="Register").click()
    pg.fill("#auth-email", "browser_probe2@t.test")
    pg.fill("#auth-username", "browser_probe2")
    pg.fill("#auth-display", "Browser Probe")
    pg.fill("#auth-password", "spudpass123")
    pg.get_by_role("button", name="Join PotatoHQ").click()
    pg.wait_for_timeout(3000)
    err = pg.evaluate("() => { const e = document.querySelector('.auth-error'); return e ? e.textContent : '(no error box)'; }")
    print("error box:", err)
    print("shell rendered:", pg.locator(".sb-brand").count() > 0)
    for m in msgs:
        print("console:", m[:200])
    b.close()
