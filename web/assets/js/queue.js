/* Queue panel ("The Crate"): upcoming tracks, recently spudded, autoplay status. */

import { player } from "./player.js";
import { store } from "./store.js";
import { shellRefs } from "./app.js";
import { el, toast, fmtDur } from "./ui.js";
import { icon } from "./icons.js";
import { wsSend } from "./ws.js";

let open = false;
let lastSignature = null;

function panelSignature(p) {
  const st = p.state;
  return JSON.stringify([
    st?.current?.videoId ?? null,
    !!st?.playing,
    st?.repeat ?? null,
    !!st?.shuffle,
    !!st?.autoplay,
    p.mode,
    p.canControl,
    (p.queue || []).map((q) => q.id).join(","),
    (p.history || []).map((h) => h.videoId).join(","),
  ]);
}

export function setQueueOpen(v) {
  open = v;
  shellRefs.queuePanel.hidden = !v;
  if (v) {
    lastSignature = null; // force a full render on open
    renderQueuePanel(player);
  }
  player.renderBar();
}

export function toggleQueue() { setQueueOpen(!open); }

export function renderQueuePanel(p = player) {
  const panel = shellRefs.queuePanel;
  if (!panel || panel.hidden) {
    player.renderBar();
    return;
  }
  // Re-render only when the music data actually changed. State broadcasts
  // arrive constantly while tracks transition; blindly rebuilding the panel
  // used to destroy the close button mid-click ("can't close the queue").
  const sig = panelSignature(p);
  if (sig === lastSignature) return;
  lastSignature = sig;
  const st = p.state;
  const can = p.canControl;

  const list = el("div", { class: "qp-list" });

  if (!p.roomId) {
    list.append(el("div", { class: "qp-empty" }, [
      el("div", { class: "empty-potato" }),
      el("span", { class: "big", text: "No bunker, no beats." }),
      el("span", { text: "Join a room to run the shared queue." }),
    ]));
  } else if (!p.queue.length) {
    list.append(el("div", { class: "qp-empty" }, [
      el("div", { class: "empty-potato" }),
      el("span", { class: "big", text: "The queue is emptier than a potato's brain." }),
      el("span", { text: st?.autoplay ? "Autoplay will keep the tunes coming." : "Autoplay is off — add tracks or turn it on." }),
    ]));
  } else {
    for (const item of p.queue) {
      const row = el("div", { class: "qp-row", "data-id": item.id });
      const img = el("img", {
        src: item.artwork || `https://i.ytimg.com/vi/${item.videoId}/default.jpg`,
        alt: "",
        loading: "lazy",
      });
      img.addEventListener("error", () => { img.src = `https://i.ytimg.com/vi/${item.videoId}/default.jpg`; }, { once: true });
      const adder = store.friends.find((f) => f.id === item.addedBy);
      const adderName = item.addedBy === store.me?.id ? "you" : (adder?.displayName || usernameById(item.addedBy, p) || "a spud");
      row.append(
        img,
        el("div", { class: "grow" }, [
          el("div", { class: "q-title", text: item.title }),
          el("div", { class: "q-sub", text: `${item.artist || "unknown artist"} · queued by ${adderName}` }),
        ]),
        el("span", { class: "q-dur", text: fmtDur(item.duration || 0) }),
        el("div", { class: "q-hover-actions" }, [
          el("button", {
            class: "btn-icon", title: "Play next", "aria-label": `Play ${item.title} next`,
            disabled: !can,
            onclick: () => wsSend({ type: "music.control", roomId: p.roomId, action: "move_top", params: { itemId: item.id } }),
          }, [icon("chevronDown", 15, "rotate")]),
          el("button", {
            class: "btn-icon", title: "Remove from queue", "aria-label": `Remove ${item.title} from queue`,
            disabled: !can,
            onclick: () => wsSend({ type: "music.control", roomId: p.roomId, action: "remove", params: { itemId: item.id } }),
          }, [icon("x", 15)]),
        ]),
      );
      list.append(row);
    }
  }

  if (p.history.length) {
    list.append(el("div", { class: "qp-section", text: "Recently spudded" }));
    for (const t of p.history) {
      const replay = el("button", {
        class: "btn-icon", title: "Queue this track again",
        "aria-label": `Queue ${t.title} again`,
        disabled: !can,
        onclick: () => {
          player.sendAdd(t);
          toast("Back on the menu. The spuds approve.", "info");
        },
      }, [icon("plus", 14)]);
      list.append(el("div", { class: "qp-row" }, [
        el("img", { src: t.artwork || `https://i.ytimg.com/vi/${t.videoId}/default.jpg`, alt: "", loading: "lazy" }),
        el("div", { class: "grow" }, [
          el("div", { class: "q-title", text: t.title }),
          el("div", { class: "q-sub", text: t.artist || "unknown artist" }),
        ]),
        t.duration ? el("span", { class: "q-dur", text: fmtDur(t.duration) }) : null,
        replay,
      ]));
    }
  }

  const autoplayToggle = el("button", {
    class: "qp-autoplay" + (st?.autoplay ? " on" : ""),
    role: "switch", "aria-checked": String(!!st?.autoplay),
    "aria-label": "Autoplay recommended tracks when the queue runs dry",
    title: "Autoplay: keeps the music going when the queue runs dry",
    disabled: !can || !p.roomId,
  }, [
    el("span", { text: "Autoplay" }),
    el("span", { class: "switch" }),
  ]);
  autoplayToggle.addEventListener("click", () => {
    wsSend({ type: "music.control", roomId: p.roomId, action: "autoplay", params: { on: !st?.autoplay } });
  });

  panel.replaceChildren(
    el("div", { class: "qp-head" }, [
      el("h3", {}, [icon("queue", 17), "The Queue"]),
      autoplayToggle,
      el("button", { class: "btn-icon", "aria-label": "Close queue", onclick: () => setQueueOpen(false) }, [icon("x", 16)]),
    ]),
    list,
  );
}

function usernameById(id, p) {
  const m = (store.channel?.members || []).find((x) => x.id === id);
  return m?.displayName || null;
}
