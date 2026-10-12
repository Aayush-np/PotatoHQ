/* Login / registration screen. */

import { api } from "./api.js";
import { el } from "./ui.js";
import { LOGO_POTATO } from "./icons.js";

export function renderAuth(root, onAuthed) {
  let mode = "login";

  const wrap = el("div", { class: "auth-wrap" });
  const card = el("div", { class: "auth-card", role: "presentation" });
  wrap.append(card);
  root.replaceChildren(wrap);

  function render() {
    const errBox = el("div", { class: "auth-error", role: "alert", hidden: true });
    const email = el("input", {
      class: "input", type: "email", id: "auth-email", autocomplete: "email",
      placeholder: mode === "login" ? "you@spudmail.com" : "Email for the HQ records",
    });
    const username = el("input", {
      class: "input", id: "auth-username", autocomplete: "username",
      placeholder: "spud_name (letters, numbers, . _ -)",
    });
    const password = el("input", {
      class: "input", type: "password", id: "auth-password",
      autocomplete: mode === "login" ? "current-password" : "new-password",
      placeholder: "••••••••",
    });
    const displayName = el("input", {
      class: "input", id: "auth-display", autocomplete: "nickname",
      placeholder: "What the other spuds call you (optional)",
    });
    const submit = el("button", { class: "btn primary", type: "submit", text: mode === "login" ? "Enter the HQ" : "Join PotatoHQ" });

    const form = el("form", { class: "auth-form", novalidate: true }, [
      el("label", {}, [el("span", { text: "Email" }), email]),
      mode === "register" ? el("label", {}, [el("span", { text: "Username" }), username]) : null,
      mode === "register" ? el("label", {}, [el("span", { text: "Display name (optional)" }), displayName]) : null,
      el("label", {}, [el("span", { text: "Password" }), password,
        mode === "register" ? el("span", { class: "hint", text: "At least 8 characters." }) : null]),
      errBox,
      submit,
    ]);

    card.replaceChildren(
      el("div", { class: "auth-brand" }, [
        el("div", { html: LOGO_POTATO, style: "width:46px;height:46px" }),
        el("h1", { html: "Potato<em>HQ</em>" }),
      ]),
      el("p", { class: "auth-tagline", text: "The unofficial headquarters of you and your spuds." }),
      el("div", { class: "auth-tabs", role: "tablist" }, [
        el("button", { type: "button", role: "tab", "aria-selected": mode === "login", text: "Sign in", onclick: () => { mode = "login"; render(); } }),
        el("button", { type: "button", role: "tab", "aria-selected": mode === "register", text: "Register", onclick: () => { mode = "register"; render(); } }),
      ]),
      form,
      el("p", { class: "auth-footer", text: "PotatoHQ — where friends go to do absolutely nothing together." }),
    );

    email.focus();

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      errBox.hidden = true;
      submit.disabled = true;
      submit.textContent = mode === "login" ? "Opening the bunker…" : "Planting the potato…";
      try {
        if (mode === "login") {
          await api.login(email.value.trim(), password.value);
        } else {
          await api.register(email.value.trim(), username.value.trim(), password.value, displayName.value.trim());
        }
        onAuthed();
      } catch (err) {
        errBox.textContent = err.message || "Couldn't reach the HQ. Try again.";
        errBox.hidden = false;
        submit.disabled = false;
        submit.textContent = mode === "login" ? "Enter the HQ" : "Join PotatoHQ";
      }
    });
  }

  render();
}
