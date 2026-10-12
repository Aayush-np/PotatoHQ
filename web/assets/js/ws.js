/* WebSocket layer: auto-reconnect with backoff, clock-skew sampling, event dispatch. */

import { emit } from "./store.js";
import { toast } from "./ui.js";

const handlers = new Map(); // type -> Set<fn>
let ws = null;
let connected = false;
let attempts = 0;
let reconnectTimer = null;
let heartbeatTimer = null;
let manuallyClosed = false;

/* event ring-buffer for support/tests: window.__potatohq.wsLog() */
const _wsLog = [];
function logEvent(event, detail) {
  _wsLog.push({ t: new Date().toISOString().slice(11, 23), event, detail });
  if (_wsLog.length > 60) _wsLog.shift();
}

export function onWs(type, fn) {
  if (!handlers.has(type)) handlers.set(type, new Set());
  handlers.get(type).add(fn);
  return () => handlers.get(type)?.delete(fn);
}

export const clock = {
  skew: 0,        // serverTime - localTime (seconds), EWMA
  ready: false,
  sample(serverTime) {
    const s = serverTime - Date.now() / 1000;
    this.skew = this.ready ? this.skew * 0.7 + s * 0.3 : s;
    this.ready = true;
  },
  serverNow() { return Date.now() / 1000 + this.skew; },
};

export function wsSend(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

export function wsConnected() { return connected; }

/** Debug snapshot of the socket layer (used by tests + support tooling). */
export function wsState() {
  return {
    connected,
    attempts,
    manuallyClosed,
    reconnectTimerActive: reconnectTimer !== null,
    socketReadyState: ws ? ws.readyState : null,
  };
}

export function wsLog() {
  return _wsLog.slice();
}

export function wsLogEvent(event, detail) {
  logEvent(event, detail);
}

function setConnected(v) {
  const was = connected;
  connected = v;
  if (was !== v) emit("ws", v);
}

export function connect() {
  manuallyClosed = false;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}/ws`);
  ws = sock;

  sock.onopen = () => {
    logEvent("open");
    attempts = 0;
    setConnected(true);
    startHeartbeat();
    handlers.get("_open")?.forEach((fn) => fn());
  };

  sock.onmessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    if (!data || typeof data.type !== "string") return;
    if (data.serverTime) clock.sample(data.serverTime);
    const set = handlers.get(data.type);
    if (set) for (const fn of set) {
      try { fn(data); } catch (err) { console.error(`[ws] handler for ${data.type}`, err); }
    }
  };

  sock.onclose = (e) => {
    logEvent("close", { code: e.code });
    stopHeartbeat();
    setConnected(false);
    ws = null;
    console.warn("[ws] closed:", e.code, e.reason || "(no reason)", "reconnect:", !manuallyClosed);
    handlers.get("_close")?.forEach((fn) => fn());
    if (!manuallyClosed) scheduleReconnect();
  };

  sock.onerror = () => { /* onclose follows */ };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  attempts += 1;
  const delay = Math.min(15000, 800 * Math.pow(1.7, Math.min(attempts - 1, 7)));
  logEvent("schedule-reconnect", { attempts, delayMs: Math.round(delay) });
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

let misses = 0;
function startHeartbeat() {
  stopHeartbeat();
  misses = 0;
  heartbeatTimer = setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    misses += 1;
    wsSend({ type: "ping" });
    if (misses >= 3) {
      toast("Spud-connection lost. Retrying…", "error");
      ws.close();
    }
  }, 15000);
}

onWs("pong", () => { misses = 0; });

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
}

export function disconnect() {
  manuallyClosed = true;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  stopHeartbeat();
  if (ws) ws.close();
  setConnected(false);
}

/** Immediate, user-initiated reconnect (banner click). */
export function reconnectNow() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  attempts = 0;
  connect();
}
