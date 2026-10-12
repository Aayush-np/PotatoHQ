/* Music discovery modal: search YouTube Music (songs, artists, albums, playlists),
   browse results, queue tracks or whole collections. */

import { api } from "./api.js";
import { player } from "./player.js";
import { store } from "./store.js";
import { el, qs, toast, fmtDur, debounce, potatoLoader } from "./ui.js";
import { icon } from "./icons.js";
import { openModal, closeModal } from "./modals.js";

const TABS = [
  { id: "songs", label: "Songs" },
  { id: "artists", label: "Artists" },
  { id: "albums", label: "Albums" },
  { id: "playlists", label: "Playlists" },
];

export function openSearch(roomId) {
  let tab = "songs";
  let query = "";
  let detail = null; // {kind, id, title, subtitle, artwork, tracks}
  let lastResults = { songs: [], artists: [], albums: [], playlists: [] };
  let token = 0;

  openModal((modal, close) => {
    const input = el("input", {
      class: "input", type: "search",
      placeholder: "Search YouTube Music… songs, artists, albums, playlists",
      "aria-label": "Search YouTube Music",
      autocomplete: "off",
    });
    const tabsBox = el("div", { class: "ms-tabs", role: "tablist" });
    const resultsBox = el("div", { class: "ms-results", role: "listbox", "aria-label": "Search results" });

    modal.append(
      el("div", { class: "modal-head" }, [
        icon("search", 18),
        el("h3", { text: "Add music to the queue" }),
        el("button", { class: "btn-icon", "aria-label": "Close search", onclick: close }, [icon("x", 17)]),
      ]),
      el("div", { style: "padding:0 18px" }, [input]),
      tabsBox,
      resultsBox,
    );
    modal.classList.add("wide");

    resultsBox.append(potatoLoader("The potato is thinking…"));

    const renderTabs = () => {
      tabsBox.replaceChildren(...TABS.map((t) =>
        el("button", {
          role: "tab", "aria-selected": tab === t.id,
          class: tab === t.id ? "active" : "",
          text: t.label,
          onclick: () => { tab = t.id; detail = null; renderTabs(); search(); },
        })
      ));
    };

    const runSearch = async () => {
      if (!query.trim()) { resultsBox.replaceChildren(emptyHint()); return; }
      if (detail) return; // detail view open; don't clobber
      token += 1;
      const my = token;
      resultsBox.replaceChildren(potatoLoader("The potato is thinking…"));
      try {
        const res = await api.musicSearch(query.trim(), tab);
        if (my !== token) return;
        lastResults[tab] = res.results || [];
        renderResults();
      } catch (e) {
        if (my !== token) return;
        resultsBox.replaceChildren(errorHint(e.message, () => search()));
      }
    };
    const search = debounce(runSearch, 320);

    const renderResults = () => {
      if (detail) return renderDetail();
      const rows = lastResults[tab] || [];
      if (!rows.length) {
        resultsBox.replaceChildren(emptyHint());
        return;
      }
      const frag = document.createDocumentFragment();
      if (tab === "songs") {
        for (const t of rows) frag.append(songRow(t));
      } else {
        for (const r of rows) frag.append(collectionRow(r));
      }
      resultsBox.replaceChildren(frag);
    };

    const songRow = (t) => {
      const img = el("img", { src: t.artwork || `https://i.ytimg.com/vi/${t.videoId}/default.jpg`, alt: "", loading: "lazy" });
      img.addEventListener("error", () => { img.src = `https://i.ytimg.com/vi/${t.videoId}/default.jpg`; }, { once: true });
      const addBtn = el("button", { class: "add-btn", "aria-label": `Queue ${t.title}` },
        [icon("plus", 13), el("span", { text: "Queue" })]);
      addBtn.addEventListener("click", () => {
        player.sendAdd(t);
        addBtn.replaceChildren(icon("check", 13), el("span", { text: "Queued" }));
        setTimeout(() => addBtn.replaceChildren(icon("plus", 13), el("span", { text: "Queue" })), 1400);
      });
      return el("div", { class: "ms-row", role: "option" }, [
        img,
        el("div", { class: "grow" }, [
          el("div", { class: "r-title", text: t.title }),
          el("div", { class: "r-sub", text: t.artist || "unknown artist" }),
        ]),
        t.duration ? el("span", { class: "r-dur", text: fmtDur(t.duration) }) : null,
        addBtn,
      ]);
    };

    const collectionRow = (r) => {
      const img = el("img", { src: r.artwork || "/favicon.svg", alt: "", loading: "lazy" });
      return el("button", { class: "ms-row", role: "option", onclick: () => openCollection(r) }, [
        img,
        el("div", { class: "grow" }, [
          el("div", { class: "r-title", text: r.title }),
          el("div", { class: "r-sub", text: r.subtitle || "" }),
        ]),
        icon("chevronRight", 16),
      ]);
    };

    const openCollection = async (r) => {
      token += 1;
      const my = token;
      detail = { kind: r.kind, id: r.id, title: r.title, subtitle: r.subtitle, artwork: r.artwork, tracks: null };
      renderDetail();
      try {
        let data;
        if (r.kind === "album") data = await api.musicAlbum(r.id);
        else if (r.kind === "playlist") data = await api.musicPlaylist(r.id);
        else data = await api.musicArtist(r.id);
        if (my !== token) return;
        detail.tracks = data.tracks || [];
        renderDetail();
      } catch (e) {
        if (my !== token) return;
        detail = null;
        resultsBox.replaceChildren(errorHint(e.message, () => { detail = null; search(); }));
      }
    };

    const renderDetail = () => {
      if (!detail) return renderResults();
      const frag = document.createDocumentFragment();
      frag.append(el("button", {
        class: "ms-back",
        onclick: () => { detail = null; renderResults(); },
      }, [icon("chevronLeft", 14), el("span", { text: "Back to results" })]));

      frag.append(el("div", { class: "ms-detail-head" }, [
        el("img", { src: detail.artwork || "/favicon.svg", alt: "" }),
        el("div", {}, [
          el("div", { class: "t", text: detail.title }),
          el("div", { class: "s", text: detail.subtitle || "" }),
        ]),
      ]));

      if (detail.tracks === null) {
        frag.append(potatoLoader("The potato is thinking…"));
        resultsBox.replaceChildren(frag);
        return;
      }
      if (detail.tracks.length) {
        frag.append(el("button", {
          class: "btn small primary queue-all-btn",
          onclick: () => {
            player.sendAddMany(detail.tracks);
            toast(`Queued ${detail.tracks.length} tracks. The bunker is thriving.`, "info");
          },
        }, [icon("plus", 14), el("span", { text: "Queue all" })]));
        for (const t of detail.tracks) frag.append(songRow(t));
      } else {
        frag.append(el("div", { class: "ms-empty" }, [
          el("div", { class: "empty-potato" }),
          el("span", { text: "Nothing playable in there. Even the potato is confused." }),
        ]));
      }
      resultsBox.replaceChildren(frag);
    };

    const emptyHint = () => el("div", { class: "ms-empty" }, [
      el("div", { class: "empty-potato" }),
      query.trim()
        ? el("span", { text: "Nothing found. Even the potato is confused." })
        : el("span", { text: "Search for a song, artist, album or playlist." }),
    ]);

    const errorHint = (msg, retry) => el("div", { class: "ms-empty" }, [
      el("span", { text: msg || "The spud couldn't reach YouTube Music." }),
      el("button", { class: "btn small", onclick: retry, text: "Try again" }),
    ]);

    input.addEventListener("input", () => {
      const v = input.value.trim();
      if (v === query) return;
      query = v;
      detail = null;
      search();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); runSearch(); }
    });

    renderTabs();
    input.focus();
  }, { wide: true, label: "Add music" });
}
