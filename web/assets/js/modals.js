/* Modal framework + PotatoHQ dialogs: create room, invite friends, profile, room settings, confirm. */

import { api } from "./api.js";
import { store, emit, applyBootstrap } from "./store.js";
import { el, toast, avatarImg, fmtLastSeen } from "./ui.js";
import { icon } from "./icons.js";
import { voice } from "./voice.js";

let activeModal = null;

export function openModal(build, { wide = false, label = "Dialog" } = {}) {
  closeModal();
  const backdrop = el("div", {
    class: "modal-backdrop",
    role: "dialog", "aria-modal": "true", "aria-label": label,
    onclick: (e) => { if (e.target === backdrop) closeModal(); },
  });
  const modal = el("div", { class: "modal" + (wide ? " wide" : "") });
  backdrop.append(modal);
  document.body.append(backdrop);
  activeModal = { backdrop, modal };
  build(modal, closeModal);
  document.addEventListener("keydown", escClose);
  const focusable = modal.querySelector("input, textarea, button");
  focusable?.focus();
  return { close: closeModal, modal };
}

function escClose(e) { if (e.key === "Escape") closeModal(); }

export function closeModal() {
  if (!activeModal) return;
  activeModal.backdrop.remove();
  activeModal = null;
  document.removeEventListener("keydown", escClose);
}

function modalShell(modal, title, bodyEl, actions = []) {
  modal.append(
    el("div", { class: "modal-head" }, [
      el("h3", { text: title }),
      el("button", { class: "btn-icon", "aria-label": "Close dialog", onclick: closeModal }, [icon("x", 17)]),
    ]),
    el("div", { class: "modal-body" }, [bodyEl]),
  );
  if (actions.length) {
    bodyEl.append(el("div", { class: "modal-actions" }, actions));
  }
}

/* ---------- create room ---------- */

export function openCreateRoom(onCreated) {
  openModal((modal, close) => {
    const name = el("input", { class: "input", placeholder: "e.g. The Starch Bunker", maxlength: 60 });
    const topic = el("input", { class: "input", placeholder: "What happens in here? (optional)", maxlength: 140 });
    const inviteBox = el("div", { class: "check-list", role: "group", "aria-label": "Invite friends" });

    const rebuildList = () => {
      if (!store.friends.length) {
        inviteBox.replaceChildren(el("p", {
          class: "empty-note",
          text: "No spuds to invite yet — add friends first, they can always use the spud-code later.",
        }));
        return;
      }
      const frag = document.createDocumentFragment();
      for (const f of store.friends) {
        const cb = el("input", { type: "checkbox", value: String(f.id) });
        frag.append(el("label", { class: "check-row" }, [
          cb, avatarImg(f, 28, { status: true }),
          el("span", { class: "name", text: f.displayName }),
          el("span", { class: "sb-sub", text: "@" + f.username }),
        ]));
      }
      inviteBox.replaceChildren(frag);
    };
    rebuildList();

    const createBtn = el("button", { class: "btn primary", text: "Dig the bunker" });
    const form = el("div", { class: "modal-form" }, [
      el("label", {}, [el("span", { text: "Room name" }), name]),
      el("label", {}, [el("span", { text: "Topic (optional)" }), topic]),
      el("div", {}, [el("span", { class: "hint", text: "Invite spuds (optional)", style: "font-size:13px;font-weight:600;color:var(--text-dim)" }), inviteBox]),
      el("div", { class: "modal-actions" }, [createBtn]),
    ]);

    modalShell(modal, "Create a bunker", form);

    createBtn.addEventListener("click", async () => {
      const n = name.value.trim();
      if (!n) { name.focus(); toast("Give the bunker a name first.", "error"); return; }
      const ids = [...inviteBox.querySelectorAll("input:checked")].map((c) => parseInt(c.value, 10));
      createBtn.disabled = true;
      createBtn.textContent = "Digging…";
      try {
        const { room } = await api.createRoom(n, topic.value.trim(), ids);
        toast(`Bunker dug. Welcome to ${room.name}.`, "info");
        close();
        onCreated?.(room);
      } catch (e) {
        toast(e.message, "error");
        createBtn.disabled = false;
        createBtn.textContent = "Dig the bunker";
      }
    });
  });
}

/* ---------- invite friends ---------- */

export function openInviteFriends(room, onDone) {
  openModal((modal, close) => {
    const existing = new Set((store.channel?.members || []).filter((m) => m.memberStatus === "active").map((m) => m.id));
    const list = el("div", { class: "check-list" });
    const sendBtn = el("button", { class: "btn primary", text: "Send invites" });
    const body = el("div", { class: "modal-form" }, [
      el("p", { class: "section-sub", text: "Only your friends can be invited. You can also share the spud-code below." }),
      el("div", { class: "code-chip", style: "align-self:flex-start", role: "button", tabindex: "0" }, [
        icon("copy", 14), el("span", { text: room.inviteCode || "…" }),
      ]),
      list,
      el("div", { class: "modal-actions" }, [sendBtn]),
    ]);

    const codeChip = body.querySelector(".code-chip");
    const copyCode = () => {
      const url = `${location.origin}/#/join/${room.inviteCode}`;
      navigator.clipboard?.writeText(url).then(
        () => toast("Spud-code link copied. Spread it wisely.", "info"),
        () => toast(`Spud-code: ${room.inviteCode}`, "info", 6000),
      );
    };
    codeChip.addEventListener("click", copyCode);
    codeChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copyCode(); } });

    const candidates = store.friends.filter((f) => !existing.has(f.id));
    if (!candidates.length) {
      list.replaceChildren(el("p", { class: "empty-note", text: "All your spuds are already here. A bunker full of friends." }));
      sendBtn.disabled = true;
    } else {
      const frag = document.createDocumentFragment();
      for (const f of candidates) {
        frag.append(el("label", { class: "check-row" }, [
          el("input", { type: "checkbox", value: String(f.id), checked: true }),
          avatarImg(f, 28, { status: true }),
          el("span", { class: "name", text: f.displayName }),
          el("span", { class: "sb-sub", text: "@" + f.username }),
        ]));
      }
      list.replaceChildren(frag);
    }

    modalShell(modal, `Invite spuds to ${room.name}`, body);

    sendBtn.addEventListener("click", async () => {
      const ids = [...list.querySelectorAll("input:checked")].map((c) => parseInt(c.value, 10));
      if (!ids.length) { toast("Pick at least one spud.", "error"); return; }
      sendBtn.disabled = true;
      try {
        const res = await api.inviteToRoom(room.id, ids);
        toast(`Invites planted for ${res.invited} spud${res.invited > 1 ? "s" : ""}.`, "info");
        close();
        onDone?.();
      } catch (e) {
        toast(e.message, "error");
        sendBtn.disabled = false;
      }
    });
  });
}

/* ---------- room settings (owner) ---------- */

export function openRoomSettings(room, onUpdated) {
  openModal((modal, close) => {
    const name = el("input", { class: "input", value: room.name, maxlength: 60 });
    const topic = el("input", { class: "input", value: room.topic || "", maxlength: 140 });
    const modeShared = el("input", { type: "radio", name: "musicmode", value: "shared", checked: room.musicMode === "shared" });
    const modeOwner = el("input", { type: "radio", name: "musicmode", value: "owner", checked: room.musicMode === "owner" });
    const saveBtn = el("button", { class: "btn primary", text: "Save changes" });
    const deleteBtn = el("button", { class: "btn danger", text: "Demolish bunker" });

    const body = el("div", { class: "modal-form" }, [
      el("label", {}, [el("span", { text: "Room name" }), name]),
      el("label", {}, [el("span", { text: "Topic" }), topic]),
      el("div", { class: "seg-control", role: "radiogroup", "aria-label": "Music control mode" }, [
        el("label", {}, [modeShared, el("span", {}, [
          el("span", { class: "t", text: "Everyone can DJ" }),
          el("span", { class: "d", text: "Any member can play, pause, skip and add music." }),
        ])]),
        el("label", {}, [modeOwner, el("span", {}, [
          el("span", { class: "t", text: "Only the owner holds the aux" }),
          el("span", { class: "d", text: "Just you control playback. Others can still chat." }),
        ])]),
      ]),
      el("div", { class: "danger-zone" }, [
        el("p", { text: "Demolishing deletes the room, its messages, queue and history. There is no un-demolish." }),
        deleteBtn,
      ]),
      el("div", { class: "modal-actions" }, [saveBtn]),
    ]);

    modalShell(modal, "Room settings", body);

    saveBtn.addEventListener("click", async () => {
      const mode = modeShared.checked ? "shared" : "owner";
      saveBtn.disabled = true;
      try {
        const { room: updated } = await api.updateRoom(room.id, {
          name: name.value.trim(), topic: topic.value.trim(), musicMode: mode,
        });
        toast("Bunker redecorated.", "info");
        onUpdated?.(updated);
        close();
      } catch (e) {
        toast(e.message, "error");
        saveBtn.disabled = false;
      }
    });

    deleteBtn.addEventListener("click", () => {
      openConfirm({
        title: "Demolish this bunker?",
        body: `${room.name} and everything in it will be gone forever. The potatoes will grieve.`,
        confirmText: "Demolish it",
        danger: true,
        onConfirm: async () => {
          try {
            await api.deleteRoom(room.id);
            toast("Bunker demolished. A moment of starch, please.", "info");
            onUpdated?.(null, true);
          } catch (e) { toast(e.message, "error"); }
        },
      });
    });
  }, { wide: false });
}

/* ---------- confirm ---------- */

export function openConfirm({ title, body, confirmText = "Confirm", danger = false, onConfirm }) {
  openModal((modal, close) => {
    const btn = el("button", { class: "btn " + (danger ? "danger" : "primary"), text: confirmText });
    const bodyEl = el("div", { class: "modal-form" }, [
      el("p", { text: body, style: "color:var(--text-dim)" }),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn ghost", text: "Never mind", onclick: close }), btn,
      ]),
    ]);
    modalShell(modal, title, bodyEl);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { await onConfirm?.(); } finally { close(); }
    });
  });
}

/* ---------- profile ---------- */

export function openProfile(userId, { isMe = false, onMessage = null, onInvite = null, onLogout = null } = {}) {
  api.getUser(userId).then(({ user }) => {
    openModal((modal, close) => {
      const body = el("div", { class: "modal-form" });

      modalShell(modal, isMe ? "Your spud profile" : user.displayName, body);

      if (isMe) {
        const displayName = el("input", { class: "input", value: user.displayName, maxlength: 40 });
        const username = el("input", { class: "input", value: user.username, maxlength: 24 });
        const curPass = el("input", { class: "input", type: "password", placeholder: "Current password", autocomplete: "current-password" });
        const newPass = el("input", { class: "input", type: "password", placeholder: "New password (8+ chars)", autocomplete: "new-password" });
        const saveBtn = el("button", { class: "btn primary", text: "Save profile" });
        const logoutBtn = el("button", { class: "btn ghost", text: "Log out" });
        const fileInput = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });

        body.append(
          el("div", { class: "profile-head" }, [
            avatarImg(user, 64, { status: false }),
            el("div", { class: "stack" }, [
              el("span", { class: "big-name", text: user.displayName }),
              el("span", { class: "sub", text: "@" + user.username + " · sprouted " + fmtLastSeen(user.createdAt ?? user.lastSeen) }),
            ]),
          ]),
          el("div", { class: "avatar-pick" }, [
            el("button", {
              class: "btn small",
              onclick: () => fileInput.click(),
            }, [icon("image", 15), el("span", { text: "Change picture" })]),
            fileInput,
          ]),
          el("label", {}, [el("span", { text: "Display name" }), displayName]),
          el("label", {}, [el("span", { text: "Username" }), username]),
          el("label", {}, [el("span", { text: "Change password (optional)" }), curPass, newPass]),
          buildAudioSection(),
          el("div", { class: "modal-actions", style: "justify-content:space-between" }, [logoutBtn, saveBtn]),
        );

        fileInput.addEventListener("change", async () => {
          const file = fileInput.files[0];
          if (!file) return;
          if (file.size > 2 * 1024 * 1024) { toast("Keep it under 2 MB, spud.", "error"); return; }
          try {
            await api.uploadAvatar(file);
            toast("Fresh face. Looking like a proper potato now.", "info");
            await refreshMe();
            body.querySelector(".avatar").src = store.me.avatarUrl;
          } catch (e) { toast(e.message, "error"); }
          fileInput.value = "";
        });

        saveBtn.addEventListener("click", async () => {
          saveBtn.disabled = true;
          try {
            const patch = { displayName: displayName.value.trim(), username: username.value.trim() };
            if (newPass.value) { patch.currentPassword = curPass.value; patch.newPassword = newPass.value; }
            await api.updateMe(patch);
            toast("Profile updated.", "info");
            await refreshMe();
            close();
          } catch (e) {
            toast(e.message, "error");
            saveBtn.disabled = false;
          }
        });

        logoutBtn.addEventListener("click", async () => {
          try { await api.logout(); } catch { /* fine */ }
          close();
          onLogout?.();
        });
      } else {
        const isFriend = store.friends.some((f) => f.id === user.id);
        const actions = [];
        if (onMessage) actions.push(el("button", { class: "btn", onclick: () => { close(); onMessage(user); } }, [icon("message", 15), el("span", { text: "Message" })]));
        if (onInvite && isFriend) actions.push(el("button", { class: "btn", onclick: () => { close(); onInvite(user); } }, [icon("userPlus", 15), el("span", { text: "Invite to this room" })]));
        actions.push(el("button", {
          class: "btn danger",
          onclick: () => {
            openConfirm({
              title: "Unfriend this spud?",
              body: `You and ${user.displayName} will no longer be spuds. Harsh, but the field is big.`,
              confirmText: "Unfriend", danger: true,
              onConfirm: async () => {
                const fr = store.friends.find((f) => f.id === user.id);
                if (fr?.frId) {
                  await api.removeFriend(fr.frId);
                  toast("Unfriended. The field is big.", "info");
                }
              },
            });
          },
        }, [icon("userX", 15), el("span", { text: "Unfriend" })]));

        body.append(
          el("div", { class: "profile-head" }, [
            avatarImg(user, 64, { status: false }),
            el("div", { class: "stack" }, [
              el("span", { class: "big-name", text: user.displayName }),
              el("span", { class: "sub", text: "@" + user.username + " · last seen " + fmtLastSeen(user.lastSeen) }),
            ]),
          ]),
          el("div", { class: "modal-actions", style: "justify-content:flex-start" }, actions),
        );
      }
    });
  }).catch((e) => toast(e.message, "error"));
}

export async function refreshMe() {
  try {
    const { user } = await api.me();
    store.me = user;
    emit("sidebar");
  } catch { /* ignore */ }
}

/* ---------- audio & devices settings ---------- */

function buildAudioSection() {
  const inputSel = el("select", { class: "input", id: "audio-input-select", "aria-label": "Microphone" });
  const outputSel = el("select", { class: "input", id: "audio-output-select", "aria-label": "Output device" });
  const echoCb = el("input", { type: "checkbox" });
  const noiseCb = el("input", { type: "checkbox" });
  const meterFill = el("div", { class: "meter-fill" });
  const meter = el("div", { class: "meter", "aria-hidden": "true" }, [meterFill]);
  const testBtn = el("button", { class: "btn small", text: "Test mic" });
  const refreshBtn = el("button", {
    class: "btn-icon", title: "Refresh device list", "aria-label": "Refresh device list",
  }, [icon("refresh", 15)]);

  echoCb.checked = voice.echoCancellation;
  noiseCb.checked = voice.noiseSuppression;
  echoCb.addEventListener("change", () => { voice.echoCancellation = echoCb.checked; });
  noiseCb.addEventListener("change", () => {
    voice.noiseSuppression = noiseCb.checked;
    toast("Noise suppression applies next time you (re)join voice.", "info");
  });

  const wrap = el("div", { class: "audio-section" }, [
    el("h4", {}, [icon("sliders", 16), "Audio & devices"]),
    el("label", { class: "audio-field" }, [
      el("span", { text: "Microphone" }),
      el("div", { class: "row" }, [inputSel, refreshBtn]),
    ]),
    el("label", { class: "audio-field" }, [
      el("span", { text: "Output device (applies to spud voices)" }),
      outputSel,
    ]),
    el("div", { class: "audio-field" }, [
      el("div", { class: "row" }, [
        el("label", { class: "check-inline" }, [echoCb, el("span", { text: "Echo cancellation" })]),
        el("label", { class: "check-inline" }, [noiseCb, el("span", { text: "Noise suppression" })]),
      ]),
      el("div", { class: "row" }, [testBtn, meter]),
      el("p", { class: "hint", text: "Push-to-talk: hold V while in voice. Tip: set per-spud volume in the voice strip." }),
    ]),
  ]);

  async function populate() {
    const { inputs, outputs, granted } = await voice.listAudioDevices();
    const defOption = (label) => el("option", { value: "", text: label });
    inputSel.replaceChildren(
      defOption("Default microphone"),
      ...inputs.map((d) => el("option", {
        value: d.deviceId,
        text: d.label || "Microphone",
        selected: voice.inputDeviceId === d.deviceId ? true : null,
      })),
    );
    outputSel.replaceChildren(
      defOption("System default"),
      ...outputs.map((d) => el("option", {
        value: d.deviceId,
        text: d.label || "Output",
        selected: voice.outputDeviceId === d.deviceId ? true : null,
      })),
    );
    if (!granted) {
      inputSel.replaceChildren(
        el("option", { value: "", text: "Click ⟳ and allow mic access to list devices" }));
      outputSel.replaceChildren(
        el("option", { value: "", text: "Click ⟳ and allow mic access to list devices" }));
    }
  }

  inputSel.addEventListener("change", async () => {
    const ok = await voice.switchInputDevice(inputSel.value);
    toast(ok ? "Microphone switched." : "Couldn't switch microphone.", ok ? "info" : "error");
  });
  outputSel.addEventListener("change", async () => {
    await voice.setOutputDevice(outputSel.value);
    toast(outputSel.value ? "Output device switched for voice." : "Back to the default output.", "info");
  });
  refreshBtn.addEventListener("click", async () => {
    if (!(await voice.ensureMicPermission())) {
      toast("Mic access is blocked — allow it in your browser.", "error");
    }
    await populate();
  });

  let testing = false;
  testBtn.addEventListener("click", async () => {
    if (testing) {
      testing = false;
      voice.stopMicTest();
      testBtn.textContent = "Test mic";
      meterFill.style.width = "0%";
      return;
    }
    const ok = await voice.startMicTest();
    if (!ok) { toast("Couldn't open the microphone.", "error"); return; }
    testing = true;
    testBtn.textContent = "Stop test";
    const tick = setInterval(() => {
      if (!document.contains(meterFill)) { clearInterval(tick); voice.stopMicTest(); return; }
      const level = Math.min(1, voice.micTestLevel() * 14);
      meterFill.style.width = `${Math.round(level * 100)}%`;
    }, 120);
  });

  populate();
  return wrap;
}

