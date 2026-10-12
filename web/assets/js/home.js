/* Home view: your spuds, friend requests, invites, join by spud-code. */

import { api } from "./api.js";
import { store, applyBootstrap, on } from "./store.js";
import { el, toast, avatarImg } from "./ui.js";
import { icon } from "./icons.js";
import { activityText } from "./sidebar.js";
import { openConfirm, openProfile } from "./modals.js";
import { toggleSidebar } from "./app.js";

export function renderHome(container, { onOpenRoom, onOpenDm, onInviteToRoom }) {
  if (!container) return;
  const menuBtn = el("button", {
    class: "btn-icon menu-btn", "aria-label": "Open sidebar",
    onclick: () => toggleSidebar(true),
  }, [icon("menu", 19)]);
  const head = el("div", { class: "home-head" }, [menuBtn]);
  const view = el("div", { class: "home", "aria-label": "Spuds home" });
  const inner = el("div", { class: "home-inner" });
  view.append(head, inner);
  container.replaceChildren(view);
  draw();

  function draw() {
    if (!container.isConnected) return;
    const frag = document.createDocumentFragment();

    // invites
    if (store.invites.length) {
      const card = el("div", { class: "card" });
      card.append(el("h2", {}, [icon("users", 19), "Invitations to bunkers"]));
      card.append(el("p", { class: "section-sub", text: "Someone wants you in their potato pile." }));
      for (const inv of store.invites) {
        card.append(el("div", { class: "card-row" }, [
          avatarImg(inv.inviter || { id: 0, avatarUrl: "/favicon.svg" }, 36, { status: false }),
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: inv.name }),
            el("div", { class: "sub", text: `Invited by ${inv.inviter ? inv.inviter.displayName : "a spud"}` }),
          ]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "btn primary small", text: "Join",
              onclick: async () => {
                try {
                  await api.acceptInvite(inv.roomId);
                  toast(`You're in ${inv.name}.`, "info");
                  await refresh();
                  onOpenRoom(inv.roomId);
                } catch (e) { toast(e.message, "error"); }
              },
            }),
            el("button", {
              class: "btn small", text: "Decline",
              onclick: async () => {
                try { await api.declineInvite(inv.roomId); await refresh(); }
                catch (e) { toast(e.message, "error"); }
              },
            }),
          ]),
        ]));
      }
      frag.append(card);
    }

    // friend requests
    if (store.requestsIn.length || store.requestsOut.length) {
      const card = el("div", { class: "card" });
      card.append(el("h2", {}, [icon("userCheck", 19), "Spud requests"]));
      card.append(el("p", { class: "section-sub", text: "Approve carefully. Potatoes never forget." }));
      for (const req of store.requestsIn) {
        card.append(el("div", { class: "card-row" }, [
          avatarImg(req.user, 36, { status: true }),
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: req.user.displayName }),
            el("div", { class: "sub", text: "@" + req.user.username + " wants to be spuds" }),
          ]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "btn primary small", text: "Accept",
              onclick: async () => {
                try { await api.acceptFriend(req.id); toast("You're spuds now.", "info"); await refresh(); }
                catch (e) { toast(e.message, "error"); }
              },
            }),
            el("button", {
              class: "btn small", text: "Decline",
              onclick: async () => {
                try { await api.declineFriend(req.id); await refresh(); }
                catch (e) { toast(e.message, "error"); }
              },
            }),
          ]),
        ]));
      }
      for (const req of store.requestsOut) {
        card.append(el("div", { class: "card-row" }, [
          avatarImg(req.user, 36, { status: true }),
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: req.user.displayName }),
            el("div", { class: "sub", text: "Your request is planted. Waiting to sprout." }),
          ]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "btn small", text: "Cancel",
              onclick: async () => {
                try { await api.cancelFriend(req.id); await refresh(); }
                catch (e) { toast(e.message, "error"); }
              },
            }),
          ]),
        ]));
      }
      frag.append(card);
    }

    // friends
    const friendsCard = el("div", { class: "card" });
    friendsCard.append(el("h2", {}, [icon("users", 19), "Your spuds"]));
    if (!store.friends.length) {
      friendsCard.append(el("div", { class: "empty-note" }, [
        el("div", { class: "empty-potato" }),
        el("span", { class: "big", text: "No spuds in your circle yet." }),
        el("span", { text: "Add your friends below and start the nonsense." }),
      ]));
    } else {
      friendsCard.append(el("p", { class: "section-sub", text: "See who's online and what they're up to." }));
      for (const f of store.friends) {
        const act = f.online ? (f.activity ? activityText(f.activity) : "Online") : "Offline";
        friendsCard.append(el("div", { class: "card-row" }, [
          avatarImg(f, 38, { status: true }),
          el("button", {
            class: "grow", style: "text-align:left;display:grid;gap:1px;min-width:0",
            onclick: () => openProfile(f.id, {
              onMessage: (u) => onOpenDm(u.id),
              onInvite: (u) => onInviteToRoom(u),
            }),
          }, [
            el("span", { class: "name", text: f.displayName }),
            el("span", { class: "sub", text: act + (f.online ? "" : " · last seen " + relativeLastSeen(f)) }),
          ]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "btn-icon", title: "Message", "aria-label": `Message ${f.displayName}`,
              onclick: async () => {
                try { const { roomId } = await api.openDm(f.id); onOpenDm(roomId, f.id); }
                catch (e) { toast(e.message, "error"); }
              },
            }, [icon("message", 17)]),
            f.activity?.roomId && store.rooms.some((r) => r.id === f.activity.roomId)
              ? el("button", {
                  class: "btn small", text: "Jump in",
                  onclick: () => onOpenRoom(f.activity.roomId),
                })
              : null,
          ]),
        ]));
      }
    }
    frag.append(friendsCard);

    // add friend + join by code
    const formsCard = el("div", { class: "card" });
    formsCard.append(el("h2", {}, [icon("userPlus", 19), "Grow the circle"]));
    const addInput = el("input", { class: "input", placeholder: "Username or email", "aria-label": "Add a spud by username or email" });
    const joinInput = el("input", { class: "input", placeholder: "e.g. Qm9nZXR0", "aria-label": "Spud-code to join a room" });
    formsCard.append(
      el("div", { class: "add-forms" }, [
        el("div", {}, [
          el("p", { class: "section-sub", text: "Add a spud", style: "margin-bottom:8px" }),
          el("div", { class: "inline-form" }, [
            addInput,
            el("button", {
              class: "btn primary", text: "Add",
              onclick: async () => {
                const q = addInput.value.trim();
                if (!q) return;
                try {
                  const res = await api.addFriend(q);
                  toast(res.autoAccepted ? "They'd already asked — you're spuds now." : "Friend request planted.", "info");
                  addInput.value = "";
                  await refresh();
                } catch (e) { toast(e.message, "error"); }
              },
            }),
          ]),
        ]),
        el("div", {}, [
          el("p", { class: "section-sub", text: "Have a spud-code?", style: "margin-bottom:8px" }),
          el("div", { class: "inline-form" }, [
            joinInput,
            el("button", {
              class: "btn primary", text: "Join",
              onclick: async () => {
                const code = joinInput.value.trim();
                if (!code) return;
                try {
                  const { room } = await api.joinByCode(code);
                  toast(`You're in ${room.name}.`, "info");
                  await refresh();
                  onOpenRoom(room.id);
                } catch (e) { toast(e.message, "error"); }
              },
            }),
          ]),
        ]),
      ]),
    );
    frag.append(formsCard);

    inner.replaceChildren(frag);
    view.classList.remove("loading");
  }

  function relativeLastSeen(f) {
    return f.lastSeen ? "a while ago" : "a while ago";
  }

  async function refresh() {
    try { applyBootstrap(await api.bootstrap()); } catch { /* offline */ }
  }

  on("presence", () => { if (!store.channel) draw(); });
  on("bootstrap", () => { if (!store.channel) draw(); });
  toggleSidebar(false);
}
