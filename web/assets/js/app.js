/* App shell: sidebar column + main column + player bar + queue panel. */

import { el } from "./ui.js";
import { LOGO_POTATO } from "./icons.js";

export const shellRefs = {};

export function buildShell(root) {
  const shell = el("div", { class: "shell" });

  const scrim = el("div", { class: "scrim", id: "scrim", "aria-hidden": "true" });

  const sidebar = el("aside", { class: "sidebar", id: "sidebar", "aria-label": "PotatoHQ sidebar" });
  const main = el("main", { class: "main" });
  const connBanner = el("div", {
    class: "conn-banner", id: "conn-banner", role: "status", hidden: true,
    title: "Click to reconnect now",
  }, [
    el("span", { class: "dot" }),
    el("span", { id: "conn-banner-text", text: "Spud-connection wobbly — reconnecting… (click to retry now)" }),
  ]);
  const channel = el("section", { class: "channel", id: "channel", "aria-label": "Channel" });

  const playerBar = el("footer", {
    class: "player-bar", id: "player-bar", role: "contentinfo", "aria-label": "Shared music player",
  });
  const queuePanel = el("div", { class: "queue-panel", id: "queue-panel", hidden: true, role: "dialog", "aria-label": "Music queue" });

  main.append(connBanner, channel, playerBar, queuePanel);
  shell.append(sidebar, main, scrim);
  root.replaceChildren(shell);

  Object.assign(shellRefs, {
    shell, sidebar, main, scrim, connBanner, channel, playerBar, queuePanel,
  });

  scrim.addEventListener("click", () => {
    shellRefs.sidebar.classList.remove("open");
    scrim.classList.remove("show");
  });

  return shellRefs;
}

export function toggleSidebar(open) {
  const { sidebar, scrim } = shellRefs;
  const willOpen = open ?? !sidebar.classList.contains("open");
  sidebar.classList.toggle("open", willOpen);
  scrim.classList.toggle("show", willOpen);
}

export function setConnectionBanner(show, unreachable = false) {
  shellRefs.connBanner.hidden = !show;
  const text = document.getElementById("conn-banner-text");
  if (text) {
    text.textContent = unreachable
      ? "The HQ is unreachable — is the server still running? (python run.py)"
      : "Spud-connection wobbly — reconnecting… (click to retry now)";
  }
}

export function brandMark(size = 34) {
  return el("div", { html: LOGO_POTATO, style: `width:${size}px;height:${size}px`, "aria-hidden": "true" });
}

