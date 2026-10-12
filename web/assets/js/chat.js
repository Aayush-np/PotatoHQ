/* Channel view: rooms and DMs — header, member strip, voice strip, messages, composer. */

import { api } from "./api.js";
import { store, emit, on } from "./store.js";
import { wsSend } from "./ws.js";
import { el, toast, avatarImg, fmtTime, fmtDay, potatoLoader } from "./ui.js";
import { icon } from "./icons.js";
import { shellRefs, toggleSidebar } from "./app.js";
import { player } from "./player.js";
import { voice } from "./voice.js";
import { openProfile, openInviteFriends, openRoomSettings, openConfirm } from "./modals.js";
import { openSearch } from "./musicsearch.js";
import { activityText } from "./sidebar.js";

const REACTIONS = ["👍", "❤️", "😂", "🥔", "🔥", "😭", "🎉", "👀", "😮", "🫡"];

let dom = null;
let typingTimers = new Map();

export function openChannel(id, kind) {
  if (store.channel) closeChannel();
  const container = shellRefs.channel;
  container.className = "channel loading";
  container.replaceChildren(potatoLoader("The potato is thinking…"));

  store.channel = {
    id, kind,
    room: null,
    members: [],
    messages: [],
    messageMap: new Map(),
    hasMore: true,
    loadingOlder: false,
    typing: new Map(),
    voice: { participants: [] },
    replyTo: null,
  };

  player.bindRoom(kind === "room" ? id : null);
  if (kind === "dm") player.unbind();

  wsSend({ type: "room.enter", roomId: id });

  // fetch history immediately (room.entered will hydrate the rest)
  api.messages(id, 0, 50).then((res) => {
    if (!store.channel || store.channel.id !== id) return;
    store.channel.hasMore = res.hasMore;
    store.channel.messages = res.messages.slice().reverse(); // chronological
    store.channel.messageMap = new Map(store.channel.messages.map((m) => [m.id, m]));
    renderChannelBody();
  }).catch((e) => {
    toast(e.message, "error");
  });

  toggleSidebar(false);
}

export function closeChannel() {
  const prev = store.channel;
  if (prev) {
    wsSend({ type: "room.exit", roomId: prev.id });
    if (voice.roomId === prev.id) voice.leave();
  }
  store.channel = null;
  dom = null;
  for (const t of typingTimers.values()) clearTimeout(t);
  typingTimers.clear();
}

/* ---------- server event handlers ---------- */

export function handleEntered(data) {
  const ch = store.channel;
  if (!ch || ch.id !== data.roomId) return;
  ch.room = data.room;
  ch.members = data.members || [];
  ch.voice = data.voice || { participants: [] };
  if (ch.kind === "room") {
    player.applySnapshot({ roomId: ch.id, ...data.music });
  }
  renderChannelBody();
  emit("sidebar");
}

export function appendMessage(msg) {
  const ch = store.channel;
  if (!ch || ch.id !== msg.roomId) return;
  if (ch.messageMap.has(msg.id)) return;
  ch.messages.push(msg);
  ch.messageMap.set(msg.id, msg);
  if (msg.kind === "text") ch.typing.delete(msg.author?.id);
  renderAppend(msg);
  if (document.visibilityState === "visible" && dom) {
    wsSend({ type: "room.read", roomId: ch.id });
  }
}

export function updateMessage(msg) {
  const ch = store.channel;
  if (!ch || ch.id !== msg.roomId) return;
  const existing = ch.messageMap.get(msg.id);
  if (existing) Object.assign(existing, msg);
  else {
    ch.messages.push(msg);
    ch.messageMap.set(msg.id, msg);
    renderAppend(msg);
    return;
  }
  replaceMessageNode(msg);
}

export function setTyping(data) {
  const ch = store.channel;
  if (!ch || ch.id !== data.roomId || data.userId === store.me?.id) return;
  const key = data.userId;
  const prev = typingTimers.get(key);
  if (prev) clearTimeout(prev);
  if (data.on) {
    ch.typing.set(key, data.name);
    const t = setTimeout(() => { ch.typing.delete(key); renderTyping(); }, 4000);
    typingTimers.set(key, t);
  } else {
    ch.typing.delete(key);
  }
  renderTyping();
}

export function setMembers(members) {
  const ch = store.channel;
  if (!ch || ch.id !== members.roomId) return;
  ch.members = members.members || [];
  renderMemberStrip();
}

export function handleRoomUpdated(room) {
  const ch = store.channel;
  if (ch && ch.id === room.id) {
    ch.room = { ...ch.room, ...room };
    player.updatePerm();
    renderChannelBody();
  }
}

export function setVoiceState(data) {
  const ch = store.channel;
  if (!ch || ch.id !== data.roomId) return;
  ch.voice = { participants: data.participants || [] };
  renderVoiceStrip();
}

export function setVoiceSpeaking(data) {
  const ch = store.channel;
  if (!ch || ch.id !== data.roomId) return;
  const p = ch.voice.participants.find((x) => x.user.id === data.userId);
  if (p) p.speaking = data.speaking;
  renderVoiceStrip();
}

export function getChannelDom() { return dom; }

/* ---------- rendering ---------- */

function renderChannelBody() {
  const ch = store.channel;
  const container = shellRefs.channel;
  if (!ch) return;
  container.className = "channel";

  // header
  const header = el("header", { class: "ch-head" });
  const menuBtn = el("button", {
    class: "btn-icon menu-btn", "aria-label": "Open sidebar",
    onclick: () => toggleSidebar(true),
  }, [icon("menu", 19)]);

  const idBox = el("div", { class: "ch-id" });
  if (ch.kind === "room") {
    idBox.append(
      el("div", { class: "ch-name" }, [
        icon("room", 17),
        el("span", { text: ch.room?.name ?? "Bunker" }),
        ch.room ? el("span", { class: "room-badge", text: ch.room.musicMode === "owner" ? "Owner DJ" : "Shared DJ" }) : null,
      ]),
      el("div", { class: "ch-topic", text: ch.room?.topic || "" }),
    );
  } else {
    const friend = store.dms.find((d) => d.roomId === ch.id)?.user;
    idBox.append(
      el("div", { class: "ch-name" }, [
        friend ? avatarImg(friend, 22, { status: true }) : icon("message", 17),
        el("span", { text: friend?.displayName ?? "Spud" }),
      ]),
      el("div", { class: "ch-topic", text: friend ? (friend.online ? (friend.activity ? activityText(friend.activity) : "Online") : "Offline") : "" }),
    );
  }

  const actions = el("div", { class: "ch-actions" });

  header.append(menuBtn, idBox, el("span", { class: "spacer" }), actions);
  renderHeaderActions(actions);
  renderHeaderCodeChip(header);

  // member strip (rooms only)
  const memberStrip = ch.kind === "room"
    ? el("div", { class: "member-strip", id: "member-strip", role: "list", "aria-label": "People in this room" })
    : null;

  // voice strip
  const voiceStrip = el("div", { id: "voice-strip" });

  // messages
  const msgsScroll = el("div", { class: "msgs", id: "msgs", role: "log", "aria-label": "Messages" });
  const typingBar = el("div", { class: "typing-bar", id: "typing-bar", "aria-live": "polite" });
  const jumpLive = el("button", {
    class: "jump-live", hidden: true, "aria-label": "Jump to the latest messages",
    onclick: () => { msgsScroll.scrollTop = msgsScroll.scrollHeight; },
  }, [icon("chevronDown", 14), el("span", { text: "Jump to latest" })]);

  // composer
  const replyBar = el("div", { id: "reply-bar", hidden: true });
  const composer = el("form", { class: "composer", id: "composer" });
  const input = el("textarea", {
    id: "composer-input", rows: 1, placeholder: "Say something spud-tacular…",
    "aria-label": "Message",
  });
  const sendBtn = el("button", { class: "send-btn", type: "submit", "aria-label": "Send message", disabled: true }, [icon("send", 17)]);
  composer.append(input, sendBtn);
  const composerWrap = el("div", { class: "composer-wrap" }, [replyBar, composer, typingBar]);

  const body = el("div", { class: "ch-body" }, [msgsScroll, jumpLive, composerWrap]);

  container.replaceChildren(header, memberStrip, voiceStrip, body);
  dom = { container, header, actions, memberStrip, voiceStrip, msgsScroll, typingBar, replyBar, composer, input, sendBtn, jumpLive };

  if (memberStrip) renderMemberStrip();
  renderVoiceStrip();

  // full message render
  renderAllMessages();
  renderTyping();

  // composer wiring (with draft persistence)
  const draftKey = `potato-draft-${ch.id}`;
  const savedDraft = localStorage.getItem(draftKey) || "";
  if (savedDraft) {
    input.value = savedDraft;
    sendBtn.disabled = !savedDraft.trim();
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }
  let typingSentAt = 0;
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
    sendBtn.disabled = !input.value.trim();
    localStorage.setItem(draftKey, input.value);
    const now = Date.now();
    if (input.value.trim() && now - typingSentAt > 2500) {
      typingSentAt = now;
      wsSend({ type: "chat.typing", roomId: ch.id, on: true });
    }
  });
  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    const replyTo = ch.replyTo?.id ?? null;
    wsSend({ type: "chat.send", roomId: ch.id, content, replyTo });
    input.value = "";
    localStorage.removeItem(draftKey);
    input.style.height = "auto";
    sendBtn.disabled = true;
    setReply(null);
    wsSend({ type: "chat.typing", roomId: ch.id, on: false });
  });

  // infinite scroll upward + jump-to-live visibility
  msgsScroll.addEventListener("scroll", () => {
    const away = msgsScroll.scrollHeight - msgsScroll.scrollTop - msgsScroll.clientHeight;
    jumpLive.hidden = away < 260;
    if (msgsScroll.scrollTop < 80 && ch.hasMore && !ch.loadingOlder) loadOlder();
  });

  msgsScroll.scrollTop = msgsScroll.scrollHeight;
}

function renderHeaderActions(actions) {
  const ch = store.channel;
  actions.replaceChildren();
  if (ch.kind === "dm") return;

  const isOwner = store.me && ch.room && ch.room.ownerId === store.me.id;

  actions.append(
    el("button", {
      class: "btn small", title: "Invite friends to this room",
      onclick: () => ch.room && openInviteFriends(ch.room),
    }, [icon("userPlus", 15), el("span", { class: "label", text: "Invite" })]),
  );

  if (isOwner) {
    actions.append(el("button", {
      class: "btn-icon", title: "Room settings", "aria-label": "Room settings",
      onclick: () => ch.room && openRoomSettings(ch.room, (updated, deleted) => {
        if (deleted) { location.hash = "#/"; return; }
        handleRoomUpdated(updated);
      }),
    }, [icon("settings", 17)]));
  }

  actions.append(el("button", {
    class: "btn-icon danger-ic", title: "Leave room", "aria-label": "Leave room",
    onclick: () => openConfirm({
      title: "Leave this bunker?",
      body: "You can come back with the spud-code, or an invite. The room keeps rocking without you.",
      confirmText: "Leave room",
      onConfirm: async () => {
        try { await api.leaveRoom(ch.id); } catch (e) { toast(e.message, "error"); }
      },
    }),
  }, [icon("exit", 17)]));
}

function renderHeaderCodeChip(header) {
  const ch = store.channel;
  if (ch.kind !== "room" || !ch.room?.inviteCode) return;
  const chip = el("button", {
    class: "code-chip", title: "Copy invite link",
    "aria-label": "Copy the spud-code invite link",
  }, [icon("copy", 13), el("span", { text: ch.room.inviteCode })]);
  chip.addEventListener("click", () => {
    const url = `${location.origin}/#/join/${ch.room.inviteCode}`;
    navigator.clipboard?.writeText(url).then(
      () => toast("Spud-code link copied. Spread it wisely.", "info"),
      () => toast(`Spud-code: ${ch.room.inviteCode}`, "info", 6000),
    );
  });
  header.append(chip);
}

function renderMemberStrip() {
  const ch = store.channel;
  const strip = dom?.memberStrip;
  if (!strip || !ch) return;
  const inVoiceIds = new Set((ch.voice?.participants || []).map((p) => p.user.id));
  const voiceInfo = new Map((ch.voice?.participants || []).map((p) => [p.user.id, p]));

  const frag = document.createDocumentFragment();
  for (const m of ch.members) {
    if (m.memberStatus !== "active") continue;
    const v = voiceInfo.get(m.id);
    const icons = [];
    if (m.role === "owner") icons.push(icon("crown", 12, "crown"));
    if (v) {
      if (v.raised) icons.push(icon("hand", 12, "raised"));
      if (v.deafened) icons.push(icon("volumeX", 12, "mic-off"));
      else if (v.muted) icons.push(icon("micOff", 12, "mic-off"));
      else icons.push(icon("headset", 12, "headset"));
    }
    const isSpeaking = (v && v.speaking) || (voice.inVoice && voice.roomId === ch.id && m.id === store.me?.id && voice.ownSpeaking && !voice.muted);
    const chip = el("button", {
      class: "member-chip" + (m.id === store.me?.id ? " me" : ""),
      title: `${m.displayName} (@${m.username})${m.online ? "" : " · offline"}`,
      "aria-label": `View profile of ${m.displayName}`,
      onclick: () => openProfile(m.id, {
        isMe: m.id === store.me?.id,
        onMessage: (u) => { location.hash = "#/"; setTimeout(() => { location.hash = "#/friends"; }, 0); },
        onInvite: (u) => toast("They're already in this bunker.", "info"),
      }),
    }, [
      avatarImg(m, 26, { status: false, speaking: isSpeaking }),
      el("span", { class: "mc-name", text: m.displayName }),
      icons.length ? el("span", { class: "mc-icons" }, icons) : null,
    ]);
    frag.append(chip);
  }
  strip.replaceChildren(frag);
}

function renderVoiceStrip() {
  const ch = store.channel;
  if (!ch || ch.kind !== "room" || !dom) return;
  const strip = dom.voiceStrip;
  const participants = ch.voice?.participants || [];
  const joined = voice.inVoice && voice.roomId === ch.id;
  strip.replaceChildren();

  const wrap = el("div", { class: "voice-strip" });

  const status = joined
    ? el("span", { class: "vd-status" + (voice.status === "connected" ? "" : " connecting") }, [
        icon(voice.status === "connected" ? "wifi" : "wifiOff", 14),
        el("span", { text: voice.status === "connected" ? "Voice spud-connected" : "Digging the tunnel…" }),
      ])
    : el("span", { class: "vd-status connecting" }, [
        icon("headset", 14),
        el("span", { text: participants.length ? `${participants.length} in voice` : "Voice is empty" }),
      ]);

  const peers = el("div", { class: "vd-peers", role: "list", "aria-label": "Voice participants" });
  for (const p of participants) {
    const isMe = p.user.id === store.me?.id;
    const speaking = p.speaking || (isMe && joined && voice.ownSpeaking && !voice.muted);
    const peerKids = [
      avatarImg(p.user, 26, { status: false, speaking }),
      el("span", { class: "vd-name", text: isMe ? "You" : p.user.displayName }),
    ];
    if (p.raised) peerKids.push(icon("hand", 13, "raised-icon"));
    if (p.listener) peerKids.push(el("span", { class: "tag", text: "listening only" }));
    else if (p.deafened) peerKids.push(el("span", { class: "tag", text: "deafened" }));
    else if (p.muted && !isMe) peerKids.push(el("span", { class: "tag", text: "muted" }));
    // per-user volume for everyone except yourself
    if (joined && !isMe) {
      const vol = el("input", {
        type: "range", min: "0", max: "200", step: "10",
        value: String(Math.round(voice.peerVolume(p.user.id) * 100)),
        title: `${p.user.displayName}'s volume`,
        "aria-label": `Volume for ${p.user.displayName}`,
      });
      vol.addEventListener("input", () => voice.setPeerVolume(p.user.id, parseInt(vol.value, 10) / 100));
      peerKids.push(el("span", { class: "vd-vol" }, [icon("volume", 12), vol]));
    }
    peers.append(el("span", { class: "vd-peer", role: "listitem" }, peerKids));
  }

  if (joined) {
    const muteBtn = el("button", {
      class: "btn small" + (voice.muted ? " mic-off-live" : ""),
      title: voice.muted ? "Unmute microphone" : "Mute microphone",
      "aria-label": voice.muted ? "Unmute microphone" : "Mute microphone",
      "aria-pressed": String(voice.muted),
      onclick: () => voice.setMuted(!voice.muted),
    }, [icon(voice.muted ? "micOff" : "mic", 15), el("span", { text: voice.muted ? "Unmute" : "Mute" })]);

    const deafenBtn = el("button", {
      class: "btn small" + (voice.deafened ? " mic-off-live" : ""),
      title: voice.deafened ? "Undeafen" : "Deafen (silence everyone, mutes your mic)",
      "aria-label": voice.deafened ? "Undeafen" : "Deafen",
      "aria-pressed": String(voice.deafened),
      onclick: () => voice.setDeafened(!voice.deafened),
    }, [icon(voice.deafened ? "volumeX" : "volume", 15), el("span", { text: voice.deafened ? "Undeafen" : "Deafen" })]);

    const pttBtn = el("button", {
      class: "btn small" + (voice.pttEnabled ? "" : " ghost-ic"),
      title: voice.pttEnabled ? "Push-to-talk on — hold V to speak" : "Enable push-to-talk (hold V to speak)",
      "aria-label": "Toggle push to talk",
      "aria-pressed": String(voice.pttEnabled),
      onclick: () => {
        voice.setPttEnabled(!voice.pttEnabled);
        toast(voice.pttEnabled ? "Push-to-talk on. Hold V to speak." : "Push-to-talk off.", "info");
      },
    }, [icon("keyboard", 15), el("span", { text: "PTT" })]);

    const handBtn = el("button", {
      class: "btn small" + (voice.raised ? " hand-raised" : ""),
      title: voice.raised ? "Lower hand" : "Raise hand",
      "aria-label": voice.raised ? "Lower hand" : "Raise hand",
      "aria-pressed": String(voice.raised),
      onclick: () => voice.setRaised(!voice.raised),
    }, [icon("hand", 15), el("span", { text: voice.raised ? "Lower" : "Hand" })]);

    const leaveBtn = el("button", {
      class: "btn small danger", title: "Leave voice",
      "aria-label": "Leave voice chat",
      onclick: () => voice.leave(),
    }, [icon("exit", 15), el("span", { text: "Leave voice" })]);

    wrap.append(
      status, peers,
      el("div", { class: "vd-controls" }, [muteBtn, deafenBtn, pttBtn, handBtn, leaveBtn]),
    );
  } else {
    const joinBtn = el("button", {
      class: "btn small primary",
      onclick: async () => {
        try {
          await voice.join(ch.id);
          toast(voice.listenerOnly
            ? "No microphone found — you're in listen-only mode."
            : "You're in voice. Say hi to the spuds.", "info");
        } catch (e) {
          toast(e.message || "Couldn't reach voice.", "error");
        }
      },
    }, [icon("mic", 15), el("span", { text: "Join voice" })]);
    wrap.append(status, peers, el("div", { class: "vd-controls" }, [joinBtn]));
  }

  strip.append(wrap);
  renderMemberStrip();
}

/* ---------- messages ---------- */

function systemIconFor(content) {
  return content.startsWith("Now spudding") || content.startsWith("Rewound") ? "music" : "potato";
}

function renderAllMessages() {
  const ch = store.channel;
  const box = dom?.msgsScroll;
  if (!box || !ch) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  box.replaceChildren();
  let prev = null;
  const frag = document.createDocumentFragment();
  for (const m of ch.messages) {
    frag.append(buildMessageNode(m, prev));
    prev = m;
  }
  box.append(frag);
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

function renderAppend(msg) {
  const ch = store.channel;
  const box = dom?.msgsScroll;
  if (!box || !ch) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
  const prev = ch.messages.length > 1 ? ch.messages[ch.messages.length - 2] : null;
  const node = buildMessageNode(msg, prev);
  box.append(node);
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

function replaceMessageNode(msg) {
  const old = dom?.msgsScroll?.querySelector(`[data-mid="${msg.id}"]`);
  if (!old) return;
  const ch = store.channel;
  const idx = ch.messages.findIndex((m) => m.id === msg.id);
  const prev = idx > 0 ? ch.messages[idx - 1] : null;
  const node = buildMessageNode(msg, prev);
  old.replaceWith(node);
}

function buildMessageNode(m, prev) {
  if (m.kind === "system") {
    return el("div", { class: "msg-system", "data-mid": m.id }, [
      icon(systemIconFor(m.content), 13),
      el("span", { text: m.content }),
    ]);
  }

  const isMine = m.author && store.me && m.author.id === store.me.id;
  const sameGroup = prev && prev.kind === "text" && prev.author && m.author &&
    prev.author.id === m.author.id && m.createdAt - prev.createdAt < 300 &&
    !m.replyTo && !prev.deleted;
  const ch = store.channel;

  const row = el("div", {
    class: "msg" + (sameGroup ? "" : " first-of-group"),
    "data-mid": m.id,
  });

  if (!sameGroup) {
    const av = avatarImg(m.author || { id: 0, avatarUrl: "/favicon.svg" }, 34, { status: false });
    av.addEventListener("click", () => m.author && openProfile(m.author.id, {}));
    row.append(av);
  } else {
    row.append(el("div", { style: "width:34px;flex:none" }));
  }

  const body = el("div", { class: "m-body" });
  if (!sameGroup) {
    body.append(el("div", { class: "m-head" }, [
      el("span", {
        class: "m-author", text: m.author ? m.author.displayName : "A spud",
        onclick: () => m.author && openProfile(m.author.id, {}),
      }),
      el("span", { class: "m-time", text: fmtTime(m.createdAt) }),
    ]));
  }

  if (m.replyTo && !m.deleted) {
    body.append(el("div", { class: "m-reply" }, [
      icon("reply", 12),
      el("span", { text: `${m.replyTo.authorName}: ${m.replyTo.deleted ? "message deleted" : m.replyTo.snippet}` }),
    ]));
  }

  if (m.deleted) {
    body.append(el("div", { class: "m-text deleted", text: "This spud was deleted." }));
  } else {
    body.append(el("div", { class: "m-text", text: m.content }));
    if (m.editedAt) body.append(el("span", { class: "m-edited", text: " (edited)" }));
  }

  // reactions
  const reactions = el("div", { class: "m-reactions" });
  for (const r of m.reactions || []) {
    const mine = r.users.includes(store.me?.id);
    const chip = el("button", {
      class: "reaction" + (mine ? " mine" : ""),
      "aria-label": `${r.emoji} reaction, ${r.users.length}`,
      onclick: () => wsSend({ type: "chat.react", messageId: m.id, emoji: r.emoji }),
    }, [el("span", { text: r.emoji }), el("span", { class: "count", text: String(r.users.length) })]);
    reactions.append(chip);
  }
  if ((m.reactions || []).length) body.append(reactions);

  // hover actions
  const actions = el("div", { class: "m-actions" });
  actions.append(el("button", {
    class: "btn-icon", title: "Add reaction", "aria-label": "Add a reaction",
    onclick: (e) => openReactionPalette(e.currentTarget, m.id),
  }, [icon("smile", 15)]));
  actions.append(el("button", {
    class: "btn-icon", title: "Reply", "aria-label": "Reply to this message",
    onclick: () => setReply(m),
  }, [icon("reply", 15)]));
  if (isMine && !m.deleted) {
    actions.append(el("button", {
      class: "btn-icon", title: "Edit", "aria-label": "Edit message",
      onclick: () => startEdit(row, m),
    }, [icon("pencil", 15)]));
    actions.append(el("button", {
      class: "btn-icon", title: "Delete", "aria-label": "Delete message",
      onclick: () => openConfirm({
        title: "Delete this message?",
        body: "It will be gone forever. Potatoes don't do undo.",
        confirmText: "Delete", danger: true,
        onConfirm: async () => wsSend({ type: "chat.delete", messageId: m.id }),
      }),
    }, [icon("trash", 15)]));
  }

  row.append(body, actions);
  return row;
}

let paletteEl = null;
function openReactionPalette(anchor, messageId) {
  closePalette();
  const rect = anchor.getBoundingClientRect();
  paletteEl = el("div", { class: "reaction-palette", role: "menu", "aria-label": "Pick a reaction" },
    REACTIONS.map((emoji) =>
      el("button", {
        role: "menuitem", "aria-label": `React with ${emoji}`,
        onclick: () => {
          wsSend({ type: "chat.react", messageId, emoji });
          closePalette();
        },
      }, [emoji])
    ));
  document.body.append(paletteEl);
  const pw = paletteEl.offsetWidth;
  const left = Math.max(8, Math.min(window.innerWidth - pw - 8, rect.left - pw / 2 + rect.width / 2));
  paletteEl.style.left = left + "px";
  paletteEl.style.top = Math.max(8, rect.top - 44) + "px";
  setTimeout(() => document.addEventListener("pointerdown", paletteDismiss, { once: true }), 0);
}
function paletteDismiss(e) { if (paletteEl && !paletteEl.contains(e.target)) closePalette(); }
function closePalette() {
  if (paletteEl) { paletteEl.remove(); paletteEl = null; document.removeEventListener("pointerdown", paletteDismiss); }
}

function startEdit(row, m) {
  const body = row.querySelector(".m-body");
  const textEl = body.querySelector(".m-text");
  if (!textEl || row.querySelector(".m-edit-box")) return;
  const ta = el("textarea", { class: "input", rows: "2", "aria-label": "Edit message" });
  ta.value = m.content;
  const save = el("button", { class: "btn small primary", text: "Save" });
  const cancel = el("button", { class: "btn small ghost", text: "Cancel" });
  const box = el("div", { class: "m-edit-box" }, [ta, el("div", { class: "m-edit-actions" }, [cancel, save])]);
  textEl.replaceWith(box);
  ta.focus();
  ta.style.height = Math.min(ta.scrollHeight + 4, 160) + "px";
  const close = () => replaceMessageNode(m);
  save.addEventListener("click", () => {
    const val = ta.value.trim();
    if (val && val !== m.content) wsSend({ type: "chat.edit", messageId: m.id, content: val });
    close();
  });
  cancel.addEventListener("click", close);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save.click(); }
    if (e.key === "Escape") close();
  });
}

function setReply(msg) {
  const ch = store.channel;
  if (!ch || !dom) return;
  ch.replyTo = msg;
  if (!msg) {
    dom.replyBar.hidden = true;
    dom.replyBar.replaceChildren();
    return;
  }
  dom.replyBar.hidden = false;
  dom.replyBar.replaceChildren(
    icon("reply", 13),
    el("span", {}, [
      el("span", { class: "who", text: `Replying to ${msg.author?.displayName ?? "a spud"}` }),
      el("span", { text: ` · ${msg.content.slice(0, 80)}` }),
    ]),
    el("button", {
      class: "btn-icon", "aria-label": "Cancel reply",
      onclick: () => setReply(null),
    }, [icon("x", 14)]),
  );
  dom.input.focus();
}

function renderTyping() {
  const ch = store.channel;
  if (!ch || !dom) return;
  const names = [...ch.typing.values()];
  const bar = dom.typingBar;
  if (!names.length) {
    bar.replaceChildren();
    return;
  }
  const label = names.length === 1
    ? `${names[0]} is typing`
    : names.length === 2
      ? `${names[0]} and ${names[1]} are typing`
      : `${names.length} spuds are typing`;
  bar.replaceChildren(
    el("span", { class: "typing-dots", "aria-hidden": "true" }, [el("i"), el("i"), el("i")]),
    el("span", { text: label + "…" })
  );
}

function loadOlder() {
  const ch = store.channel;
  if (!ch || !dom || ch.loadingOlder || !ch.messages.length) return;
  ch.loadingOlder = true;
  const box = dom.msgsScroll;
  const beforeHeight = box.scrollHeight;
  const beforeTop = box.scrollTop;
  const oldest = ch.messages[0].id;
  api.messages(ch.id, oldest, 50).then((res) => {
    if (!store.channel || store.channel !== ch) return;
    ch.hasMore = res.hasMore;
    const fresh = res.messages.slice().reverse().filter((m) => !ch.messageMap.has(m.id));
    ch.messages = fresh.concat(ch.messages);
    fresh.forEach((m) => ch.messageMap.set(m.id, m));
    renderAllMessages();
    box.scrollTop = box.scrollHeight - beforeHeight + beforeTop;
  }).catch(() => { /* ignore */ })
    .finally(() => { ch.loadingOlder = false; });
}

on("voice", () => {
  if (store.channel && dom) renderVoiceStrip();
});
