/* DOM helpers, time formatting, avatars, toasts. */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v; // only ever used with trusted static markup
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  const kids = Array.isArray(children) ? children : [children];
  for (const c of kids) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function qs(sel, root = document) { return root.querySelector(sel); }
export function qsa(sel, root = document) { return [...root.querySelectorAll(sel)]; }

export function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function fmtDay(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const yesterday = new Date(Date.now() - 864e5);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

export function fmtDur(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  sec = Math.round(sec);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtLastSeen(ts) {
  if (!ts) return "a while ago";
  const diff = Date.now() / 1000 - ts;
  if (diff < 120) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  return `${Math.floor(diff / 86400)} days ago`;
}

export function avatarImg(user, size = 32, opts = {}) {
  const img = el("img", {
    class: "avatar" + (opts.speaking ? " speaking" : ""),
    src: user.avatarUrl,
    alt: "",
    width: size,
    height: size,
    style: `width:${size}px;height:${size}px`,
    loading: "lazy",
  });
  img.addEventListener("error", () => {
    img.src = "/api/users/" + user.id + "/avatar?v=fallback";
  }, { once: true });
  const wrap = el("span", { class: "avatar-stack" + (opts.cls ? " " + opts.cls : "") }, [img]);
  if (opts.status !== false) {
    wrap.append(el("span", {
      class: "status-dot" + (user.online ? " online" : ""),
      title: user.online ? "Online" : "Offline",
    }));
  }
  return wrap;
}

let toastRoot = null;
export function toast(text, level = "info", ms = 3800) {
  if (!toastRoot) {
    toastRoot = el("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastRoot);
  }
  const ic = level === "error" ? "x" : "info";
  const t = el("div", { class: `toast ${level}` }, [iconEl(ic), el("span", { text })]);
  toastRoot.append(t);
  const remove = () => {
    t.classList.add("leaving");
    setTimeout(() => t.remove(), 220);
  };
  const timer = setTimeout(remove, ms);
  t.addEventListener("click", () => { clearTimeout(timer); remove(); });
  while (toastRoot.children.length > 4) toastRoot.firstChild.remove();
}

import { icon } from "./icons.js";
function iconEl(...a) { return icon(...a); }

export function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export function throttle(fn, ms) {
  let last = 0;
  return (...args) => {
    const now = Date.now();
    if (now - last >= ms) {
      last = now;
      fn(...args);
    }
  };
}

export function potatoLoader(text = "The potato is thinking…") {
  return el("div", { class: "ms-loading", role: "status" }, [
    el("div", { class: "boot-potato" }),
    el("span", { text }),
  ]);
}
