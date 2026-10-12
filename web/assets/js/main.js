/* PotatoHQ entry point: boot, routing, realtime wiring. */

import { api } from "./api.js";
import { store, on, applyBootstrap, setPresence, setUnread, bumpRoomLiveness, emit } from "./store.js";
import { connect, disconnect, onWs, wsSend, reconnectNow, wsState, wsLog, wsLogEvent } from "./ws.js";
import { el, toast, debounce } from "./ui.js";
import { icon } from "./icons.js";
import { renderAuth } from "./auth.js";
import { buildShell, shellRefs, setConnectionBanner, toggleSidebar } from "./app.js";
import { initSidebar } from "./sidebar.js";
import { renderHome } from "./home.js";
import * as chat from "./chat.js";
import { player } from "./player.js";
import { voice, setOwnIdProvider } from "./voice.js";
import { openCreateRoom, openProfile, closeModal } from "./modals.js";
import { openSearch } from "./musicsearch.js";

const root = document.getElementById("app");

/* ---------- boot ---------- */

(async function boot() {
  try {
    const { user } = await api.me();
    store.me = user;
    await startApp();
  } catch {
    renderAuth(root, async () => {
      try {
        const b = await api.bootstrap();
        store.me = b.user;
        applyBootstrap(b);
      } catch { /* bootstrapped below */ }
      await startApp();
    });
  }
})();

async function startApp() {
  setOwnIdProvider(() => store.me?.id ?? 0);

  const shell = buildShell(root);
  shellRefs.connBanner.addEventListener("click", reconnectNow);
  initSidebar({
    onNav: (target) => { location.hash = "#/" + target; },    onNewRoom: () => openCreateRoom((room) => { location.hash = `#/room/${room.id}`; }),
    onProfileMenu: () => store.me && openProfile(store.me.id, {
      isMe: true,
      onLogout: () => logout(),
    }),
  });
  player.buildBar();

  try { applyBootstrap(await api.bootstrap()); } catch { /* offline */ }

  wireRealtime();
  connect();

  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", () => {
    if (voice.inVoice) voice.leave();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && store.channel) {
      wsSend({ type: "room.read", roomId: store.channel.id });
    }
  });

  route();

  // Ctrl/Cmd+K — quick music search for the bound room
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (player.roomId) openSearch(player.roomId);
    }
  });

  // installable app: register the service worker for offline shell caching
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* dev / unsupported */ });
  }
}

function logout() {
  voice.leave();
  closeModal();
  chat.closeChannel();
  player.unbind();
  disconnect();
  store.me = null;
  location.hash = "#/";
  renderAuth(root, async () => {
    try {
      const b = await api.bootstrap();
      store.me = b.user;
      applyBootstrap(b);
    } catch { /* ignore */ }
    await startApp();
  });
}

/* ---------- routing ---------- */

function route() {
  if (!store.me) return; // logged out — the auth view owns the screen
  const hash = location.hash || "#/";
  const parts = hash.replace(/^#\//, "").split("/").filter(Boolean);

  if (parts[0] === "join" && parts[1]) {
    handleJoinCode(parts[1]);
    return;
  }

  toggleSidebar(false);

  if (parts[0] === "room" && parts[1]) {
    const id = parseInt(parts[1], 10);
    if (!store.channel || store.channel.id !== id || store.channel.kind !== "room") {
      chat.openChannel(id, "room");
    }
    return;
  }
  if (parts[0] === "dm" && parts[1]) {
    const id = parseInt(parts[1], 10);
    if (!store.channel || store.channel.id !== id || store.channel.kind !== "dm") {
      chat.openChannel(id, "dm");
    }
    return;
  }

  // home
  if (store.channel) {
    chat.closeChannel();
    player.unbind();
  }
  renderHome(shellRefsSafe(), {
    onOpenRoom: (id) => { location.hash = `#/room/${id}`; },
    onOpenDm: (roomId) => { location.hash = `#/dm/${roomId}`; },
    onInviteToRoom: () => toast("Open a bunker first, then invite from there.", "info"),
  });
  store.channel = null;
  emit("sidebar");
}

function shellRefsSafe() {
  return document.getElementById("channel");
}

async function handleJoinCode(code) {
  try {
    const { room } = await api.joinByCode(code);
    toast(`You're in ${room.name}.`, "info");
    location.hash = `#/room/${room.id}`;
  } catch (e) {
    toast(e.message, "error");
    location.hash = "#/";
  }
}

/* ---------- realtime wiring ---------- */

let wired = false;
let hqProbeTimer = null;
let hqUnreachable = false; // last health-probe verdict

function startHqProbe() {
  if (hqProbeTimer) return;
  wsLogEvent("probe-start");
  hqProbeTimer = setInterval(async () => {
    try {
      await fetch("/api/health", { headers: { "X-Potato": "1" } });
      hqUnreachable = false;
      setConnectionBanner(true, false); // server reachable, just the socket cycling
      wsLogEvent("probe-tick", { reachable: true });
    } catch {
      hqUnreachable = true;
      setConnectionBanner(true, true); // server itself is down
      wsLogEvent("probe-tick", { reachable: false });
    }
  }, 6000);
}

function stopHqProbe() {
  if (hqProbeTimer) { clearInterval(hqProbeTimer); hqProbeTimer = null; }
}

function wireRealtime() {
  if (wired) return;
  wired = true;
  const refetchBootstrap = debounce(async () => {
    try { applyBootstrap(await api.bootstrap()); } catch { /* offline */ }
  }, 250);

  onWs("sync", (d) => refetchBootstrap());

  onWs("presence", (d) => setPresence(d.user));

  onWs("room.entered", (d) => chat.handleEntered(d));

  onWs("room.message", (d) => {
    chat.appendMessage(d.message);
    // keep DM ordering fresh
    const dm = store.dms.find((x) => x.roomId === d.message.roomId);
    if (dm) {
      dm.lastAt = d.message.createdAt;
      store.dms.sort((a, b) => b.lastAt - a.lastAt);
      emit("sidebar");
    }
  });

  onWs("message.updated", (d) => chat.updateMessage(d.message));

  onWs("typing", (d) => chat.setTyping(d));

  onWs("unread.update", (d) => setUnread(d.roomId, d.count));

  onWs("room.members", (d) => chat.setMembers(d));

  onWs("room.updated", (d) => {
    chat.handleRoomUpdated(d.room);
    const r = store.rooms.find((x) => x.id === d.room.id);
    if (r) Object.assign(r, d.room);
    emit("sidebar");
  });

  onWs("room.kicked", (d) => {
    toast("You've been sent back to the field.", "error");
    handleChannelGone(d.roomId);
  });

  onWs("room.deleted", (d) => {
    toast("The bunker was demolished.", "info");
    handleChannelGone(d.roomId);
  });

  onWs("voice.state", (d) => {
    bumpRoomLiveness(d.roomId, { voice: (d.participants || []).length });
    if (store.channel && store.channel.id === d.roomId) chat.setVoiceState(d);
  });

  onWs("voice.speaking", (d) => {
    if (store.channel && store.channel.id === d.roomId) chat.setVoiceSpeaking(d);
  });

  onWs("music.state", (d) => {
    const playing = !!(d.state && d.state.current && d.state.playing);
    bumpRoomLiveness(d.roomId, { music: playing });
    player.applySnapshot(d);
  });

  onWs("music.tick", (d) => player.applyTick(d));

  onWs("toast", (d) => toast(d.text, d.level || "info"));

  onWs("_open", () => {
    setConnectionBanner(false);
    stopHqProbe();
    hqUnreachable = false;
    refetchBootstrap();
    // re-enter whatever we're looking at + rejoin voice
    if (store.channel) wsSend({ type: "room.enter", roomId: store.channel.id });
    voice.rejoinAfterReconnect();
  });

  onWs("_close", () => {
    setConnectionBanner(true, hqUnreachable);
    startHqProbe();
  });

  on("ws", (connected) => {
    store.wsConnected = connected;
    if (connected) {
      hqUnreachable = false;
      stopHqProbe();
    }
    setConnectionBanner(!connected, hqUnreachable);
  });
}

function handleChannelGone(roomId) {
  if (store.channel && store.channel.id === roomId) {
    chat.closeChannel();
    player.unbind();
    if (voice.roomId === roomId) voice.leave();
  }
  location.hash = "#/";
}

/* Debug/testing hook (also handy for support tooling). */
window.__potatohq = {
  store, player, voice,
  send: wsSend,
  wsConnected: () => store.wsConnected,
  wsState,
  wsLog,
};

