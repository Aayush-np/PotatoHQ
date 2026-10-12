/* Sidebar: brand, navigation, rooms, DMs, user footer. */

import { store, on } from "./store.js";
import { el, avatarImg, qs } from "./ui.js";
import { icon } from "./icons.js";
import { brandMark, shellRefs, toggleSidebar } from "./app.js";

export function initSidebar({ onNav, onNewRoom, onProfileMenu }) {
  const { sidebar } = shellRefs;

  sidebar.replaceChildren(
    el("div", { class: "sb-brand" }, [brandMark(34), el("h1", { html: "Potato<em>HQ</em>" })]),
    el("nav", { class: "sb-nav" }, [
      el("button", {
        class: "sb-item", id: "nav-home", onclick: () => onNav(""),
        "aria-label": "Spuds, friends and invitations",
      }, [icon("users", 18), el("span", { text: "Spuds" }), el("span", { class: "badge", id: "nav-badge", hidden: true })]),
    ]),
    el("div", { class: "sb-scroll" }, [
      el("div", { class: "sb-section" }, [
        el("div", { class: "sb-section-head" }, [
          el("span", { text: "Bunkers" }),
          el("button", {
            class: "btn-icon", title: "Create a room", "aria-label": "Create a room",
            onclick: () => onNewRoom(),
          }, [icon("plus", 17)]),
        ]),
        el("div", { class: "sb-rooms-list", id: "sb-rooms" }),
      ]),
      el("div", { class: "sb-section" }, [
        el("div", { class: "sb-section-head" }, [el("span", { text: "Spud messages" })]),
        el("div", { class: "sb-dms-list", id: "sb-dms" }),
      ]),
    ]),
    el("footer", { class: "sb-user" }, [el("div", { id: "sb-user-inner" })]),
  );

  on("bootstrap", renderSidebar);
  on("sidebar", renderSidebar);
  renderSidebar();

  function renderSidebar() {
    renderRooms();
    renderDms();
    renderUser();
    renderBadge();
  }

  function currentRouteId() {
    if (store.channel) return { id: store.channel.id, kind: store.channel.kind };
    return {};
  }

  function renderRooms() {
    const box = qs("#sb-rooms", sidebar);
    if (!store.rooms.length) {
      box.replaceChildren(el("div", { class: "sb-empty", text: "No bunkers yet. Dig one." }));
      return;
    }
    const cur = currentRouteId();
    const frag = document.createDocumentFragment();
    for (const room of store.rooms) {
      const unread = store.unread[room.id] || 0;
      const live = room.live || {};
      const row = el("button", {
        class: "sb-row" + (cur.kind === "room" && cur.id === room.id ? " active" : ""),
        onclick: () => onNav(`room/${room.id}`),
        title: room.name + (room.topic ? " — " + room.topic : ""),
      }, [
        icon("room", 17),
        el("span", { class: "stack" }, [el("span", { class: "sb-name", text: room.name })]),
        live.music ? el("span", { class: "live-music", title: "Music is playing", "aria-label": "Music playing" },
          [el("i"), el("i"), el("i")]) : null,
        live.voice ? el("span", { class: "voice-chip", title: `${live.voice} in voice` },
          [icon("headset", 13), String(live.voice)]) : null,
        unread ? el("span", { class: "unread-dot", text: unread > 99 ? "99+" : String(unread) }) : null,
      ]);
      frag.append(row);
    }
    box.replaceChildren(frag);
  }

  function renderDms() {
    const box = qs("#sb-dms", sidebar);
    if (!store.dms.length) {
      box.replaceChildren(el("div", { class: "sb-empty", text: "No DMs. Slide into some." }));
      return;
    }
    const cur = currentRouteId();
    const frag = document.createDocumentFragment();
    for (const dm of store.dms) {
      const unread = store.unread[dm.roomId] || 0;
      const row = el("button", {
        class: "sb-row" + (cur.kind === "dm" && cur.id === dm.roomId ? " active" : ""),
        onclick: () => onNav(`dm/${dm.roomId}`),
      }, [
        avatarImg(dm.user, 30, { status: true }),
        el("span", { class: "stack" }, [
          el("span", { class: "sb-name", text: dm.user.displayName }),
          el("span", {
            class: "sb-sub",
            text: dm.user.online
              ? (dm.user.activity ? activityText(dm.user.activity) : "Online")
              : "Offline",
          }),
        ]),
        unread ? el("span", { class: "unread-dot", text: unread > 99 ? "99+" : String(unread) }) : null,
      ]);
      frag.append(row);
    }
    box.replaceChildren(frag);
  }

  function renderUser() {
    const box = qs("#sb-user-inner", sidebar);
    if (!store.me) return;
    box.replaceChildren(
      avatarImg(store.me, 36, { status: false }),
      el("span", { class: "stack" }, [
        el("span", { class: "name", text: store.me.displayName }),
        el("span", { class: "sub", text: "@" + store.me.username }),
      ]),
      el("button", {
        class: "btn-icon", title: "Profile & settings", "aria-label": "Profile and settings",
        onclick: () => onProfileMenu(),
      }, [icon("dots", 18)]),
    );
  }

  function renderBadge() {
    const invites = store.invites.length + store.requestsIn.length;
    const badge = qs("#nav-badge", sidebar);
    const home = qs("#nav-home", sidebar);
    const active = !store.channel;
    home.classList.toggle("active", active);
    badge.hidden = invites === 0;
    badge.textContent = String(invites);
  }
}

export function activityText(activity) {
  if (!activity) return "";
  if (activity.type === "voice") return `In voice · ${activity.label}`;
  if (activity.type === "room") return `Hanging in ${activity.label}`;
  return "";
}
