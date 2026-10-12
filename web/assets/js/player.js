/* Client-side synchronized music player.

The server owns playback truth; this module:
  - binds to one room's music session (the persistent bottom bar),
  - drives the YouTube embedded player (hidden behind the album artwork —
    the audio plays, the video is never shown),
  - interpolates progress locally between server events,
  - self-heals drift by seeking when |local - expected| grows,
  - reports genuine ENDED / DURATION / ERROR events back to the server,
  - handles autoplay-blocked with a one-tap gesture fallback that respects
    the shared state (never plays locally while the room is paused).
*/

import { api } from "./api.js";
import { store, on } from "./store.js";
import { wsSend, clock } from "./ws.js";
import { el, toast, fmtDur } from "./ui.js";
import { icon } from "./icons.js";
import { shellRefs } from "./app.js";
import { renderQueuePanel, setQueueOpen } from "./queue.js";
import { openSearch } from "./musicsearch.js";

const DRIFT_SEEK_S = 3;
const VOLUME_KEY = "potato-volume";
const DEFAULT_VOLUME = 55;

let ytApiPromise = null;
function loadYTApi() {
  if (ytApiPromise) return ytApiPromise;
  ytApiPromise = new Promise((resolve) => {
    if (window.YT && window.YT.Player) return resolve(window.YT);
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      resolve(window.YT);
    };
    const tag = document.createElement("script");
    tag.src = "https://www.youtube.com/iframe_api";
    document.head.append(tag);
  });
  return ytApiPromise;
}

class PotatoPlayer {
  constructor() {
    this.roomId = null;
    this.state = null;
    this.queue = [];
    this.history = [];
    this.mode = "shared";
    this.canControl = false;
    this.isOwner = false;
    this.yt = null;
    this.ytReady = false;
    this.loadedVideo = null;
    this.reportedDurationFor = null;
    this.blocked = false;
    this.scrubbing = false;
    this.lastSelfHeal = 0;
    this.raf = 0;
    this.ui = {};
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        this.fetchState();
        this.syncYT();
      }
    });
  }

  /* ---------- binding ---------- */

  bindRoom(roomId) {
    if (this.roomId === roomId) {
      this.fetchState();
      return;
    }
    this.roomId = roomId;
    this.state = null;
    this.queue = [];
    this.history = [];
    this.loadedVideo = null;
    this.updatePerm();
    this.renderBar();
    this.fetchState();
  }

  unbind() {
    this.roomId = null;
    this.state = null;
    this.queue = [];
    this.history = [];
    this.loadedVideo = null;
    setQueueOpen(false);
    this.renderBar();
    this.syncYT();
  }

  updatePerm() {
    const ch = store.channel;
    if (ch && ch.room && ch.id === this.roomId) {
      this.isOwner = store.me && ch.room.ownerId === store.me.id;
      this.canControl = this.isOwner || ch.room.musicMode === "shared";
      this.mode = ch.room.musicMode;
    }
  }

  async fetchState() {
    if (!this.roomId) return;
    try {
      const snap = await api.musicState(this.roomId);
      this.applySnapshot({ roomId: this.roomId, ...snap });
    } catch { /* not a member / offline */ }
  }

  /* ---------- server state application ---------- */

  applySnapshot(data) {
    if (data.roomId !== this.roomId) return;
    this.state = data.state;
    this.queue = data.queue || [];
    this.history = data.history || [];
    this.mode = data.mode || this.mode;
    this.updatePerm();
    this.renderBar();
    renderQueuePanel(this);
    this.syncYT();
  }

  applyTick(d) {
    if (d.roomId !== this.roomId) return;
    if (!this.state || !this.state.current) { this.fetchState(); return; }
    if (d.version !== this.state.version || d.videoId !== this.state.current.videoId) {
      this.fetchState();
      return;
    }
    this.state.playing = !!d.playing;
    this.state.position = d.position;
    this.state.anchor = d.anchor;
    this.state.serverTime = d.serverTime;
    this.driftCheck(true);
  }

  /* ---------- position math ---------- */

  expectedPosition() {
    const st = this.state;
    if (!st || !st.current) return 0;
    if (!st.playing) return st.position;
    const serverNow = clock.serverNow();
    return Math.max(0, st.position + Math.max(0, serverNow - st.anchor));
  }

  duration() {
    const st = this.state;
    if (!st || !st.current) return 0;
    if (st.current.duration) return st.current.duration;
    if (this.ytReady && this.yt.getDuration) {
      const d = this.yt.getDuration();
      if (d > 0) return d;
    }
    return 0;
  }

  /* ---------- YouTube player (audio-only, hidden behind artwork) ---------- */

  async ensureYT() {
    if (this.yt !== null) return;
    try {
      const YT = await loadYTApi();
      this.yt = new YT.Player(shellRefs.ytMount, {
        width: "200",
        height: "200",
        playerVars: {
          playsinline: 1,
          controls: 0,
          disablekb: 1,
          modestbranding: 1,
          rel: 0,
          fs: 0,
          iv_load_policy: 3,
          origin: location.origin,
        },
        events: {
          onReady: () => {
            this.ytReady = true;
            const iframe = this.yt.getIframe?.();
            if (iframe) {
              iframe.setAttribute("allow", "autoplay; encrypted-media");
              iframe.setAttribute("tabindex", "-1");
              iframe.setAttribute("aria-hidden", "true");
            }
            this.applyVolume();
            this.syncYT();
          },
          onStateChange: (e) => this.onYTState(e),
          onError: (e) => this.onYTError(e),
          onAutoplayBlocked: () => this.setBlocked(true),
        },
      });
    } catch (e) {
      console.warn("[player] YT failed to load", e);
      this.yt = false;
    }
  }

  onYTState(e) {
    const YTState = window.YT?.PlayerState;
    if (YTState && e.data === YTState.PLAYING) {
      this.setBlocked(false);
      const dur = this.yt.getDuration();
      if (
        this.loadedVideo && dur > 0 && this.reportedDurationFor !== this.loadedVideo &&
        this.roomId && this.state?.current?.videoId === this.loadedVideo
      ) {
        this.reportedDurationFor = this.loadedVideo;
        wsSend({ type: "music.duration", roomId: this.roomId, videoId: this.loadedVideo, duration: dur });
      }
    }
    if (YTState && e.data === YTState.ENDED) {
      if (this.roomId && this.loadedVideo) {
        const dur = this.yt.getDuration?.() || this.state?.current?.duration || 0;
        wsSend({ type: "music.ended", roomId: this.roomId, videoId: this.loadedVideo, duration: dur });
      }
    }
  }

  onYTError(e) {
    if (this.suppressEmbedErrors) return; // test mode: don't report embed failures
    if (this.roomId && this.loadedVideo) {
      console.warn("[player] YT error", e.data);
      wsSend({ type: "music.error", roomId: this.roomId, videoId: this.loadedVideo, code: e.data });
    }
  }

  /* Autoplay-blocked handling: the browser refused a scripted play. No button —
     the user just taps anywhere on the page once (a gentle toast explains it)
     and we ONLY follow through if the room is actually playing, so local audio
     can never fall out of sync with the shared state. */
  setBlocked(v) {
    this.blocked = v;
    if (v && this.state?.current && this.state.playing) {
      const now = Date.now();
      if (now - (this._lastBlockHint || 0) > 30000) {
        this._lastBlockHint = now;
        toast("Tap anywhere to start listening", "info", 6000);
      }
    }
    if (v) {
      const release = () => {
        document.removeEventListener("pointerdown", release);
        if (!this.blocked) return;
        if (this.ytReady && this.state?.current && this.state.playing) {
          this.yt.playVideo();
        } else {
          // room is paused (or idle): accept the gesture, stay in sync, no sound
          this.blocked = false;
        }
      };
      document.addEventListener("pointerdown", release, { once: true });
    }
  }

  syncYT() {
    const st = this.state;
    if (!st || !st.current) {
      if (this.ytReady) { try { this.yt.stopVideo(); } catch { /* ignore */ } }
      this.loadedVideo = null;
      return;
    }
    this.ensureYT();
    if (!this.ytReady) return;

    const pos = Math.max(0, this.expectedPosition());
    if (this.loadedVideo !== st.current.videoId) {
      this.loadedVideo = st.current.videoId;
      this.reportedDurationFor = null;
      try {
        this.yt.loadVideoById({ videoId: st.current.videoId, startSeconds: Math.max(0, pos - 0.35) });
        if (!st.playing) setTimeout(() => { try { this.yt.pauseVideo(); } catch { } }, 300);
      } catch { /* player mid-teardown */ }
      return;
    }
    try {
      const s = this.yt.getPlayerState();
      const playing = st.playing;
      if (playing && (s === 2 || s === 5 || s === -1 || s === 0)) this.yt.playVideo();
      if (!playing && s === 1) this.yt.pauseVideo();
      if (!playing && s === 1) this.setBlocked(false);
      if (s === 1 || s === 2) {
        const cur = this.yt.getCurrentTime();
        if (Math.abs(cur - pos) > DRIFT_SEEK_S) this.yt.seekTo(pos, true);
      }
    } catch { /* ignore */ }
  }

  driftCheck() {
    const st = this.state;
    if (!st || !st.current || !st.playing || !this.ytReady) return;
    try {
      const s = this.yt.getPlayerState();
      if (s !== 1) return;
      const pos = this.expectedPosition();
      const cur = this.yt.getCurrentTime();
      const now = Date.now();
      if (Math.abs(cur - pos) > DRIFT_SEEK_S && now - this.lastSelfHeal > 2500) {
        this.lastSelfHeal = now;
        this.yt.seekTo(pos, true);
      }
    } catch { /* ignore */ }
  }

  /* ---------- volume (local only) ---------- */

  applyVolume() {
    const raw = parseInt(localStorage.getItem(VOLUME_KEY) ?? String(DEFAULT_VOLUME), 10);
    this.volume = isFinite(raw) ? Math.max(0, Math.min(100, raw)) : DEFAULT_VOLUME;
    this.mutedLocal = localStorage.getItem(VOLUME_KEY + "-muted") === "1";
    this.pushVolumeToYT();
    this.renderVolume();
  }

  pushVolumeToYT() {
    if (this.ytReady) {
      try {
        this.yt.setVolume(this.mutedLocal ? 0 : this.volume);
        this.mutedLocal ? this.yt.mute() : this.yt.unMute();
      } catch { /* ignore */ }
    }
  }

  setVolume(v, muted) {
    this.volume = typeof v === "number" ? v : this.volume;
    if (typeof muted === "boolean") this.mutedLocal = muted;
    if (this.mutedLocal) this.volume = Math.max(0, Math.min(100, this.volume));
    localStorage.setItem(VOLUME_KEY, String(this.volume));
    localStorage.setItem(VOLUME_KEY + "-muted", this.mutedLocal ? "1" : "0");
    this.pushVolumeToYT();
    this.renderVolume();
  }

  /* ---------- controls ---------- */

  send(action, params = {}) {
    if (!this.roomId) return;
    if (!this.canControl) { toast("The room owner has the aux cable right now.", "error"); return; }
    wsSend({ type: "music.control", roomId: this.roomId, action, params });
  }

  sendAdd(track) {
    if (!this.roomId) return;
    if (!this.canControl) { toast("The room owner has the aux cable right now.", "error"); return; }
    wsSend({ type: "music.control", roomId: this.roomId, action: "add", params: { track } });
  }

  sendAddMany(tracks) {
    if (!this.roomId || !tracks.length) return;
    if (!this.canControl) { toast("The room owner has the aux cable right now.", "error"); return; }
    wsSend({ type: "music.control", roomId: this.roomId, action: "add", params: { tracks } });
  }

  openOnYouTube() {
    const vid = this.state?.current?.videoId;
    if (vid) window.open(`https://www.youtube.com/watch?v=${vid}`, "_blank", "noopener");
  }

  /* ---------- UI: bar ---------- */

  buildBar() {
    const bar = shellRefs.playerBar;

    // Add music — big and obvious, on the left of the player
    const addBtn = el("button", {
      class: "btn primary add-music-btn",
      title: "Search and add music (Ctrl+K)",
      "aria-label": "Search and add music",
      onclick: () => this.roomId && openSearch(this.roomId),
    }, [icon("plus", 15), el("span", { text: "Add music" })]);

    // artwork (with the hidden YT player behind it + a "why is it quiet" badge)
    const art = el("div", { class: "pb-art" });
    const artImg = el("img", { alt: "", hidden: true });
    const artFallback = el("div", { class: "art-fallback", "aria-hidden": "true" });
    const mutedBadge = el("div", {
      class: "pb-muted-badge", hidden: true,
      title: "Music is muted — click the speaker button or move the volume slider",
      "aria-label": "Music is muted",
    }, [icon("volumeX", 13)]);
    const ytHost = el("div", { class: "pb-yt-host", "aria-hidden": "true" }, [el("div", { id: "yt-player" })]);
    art.append(artImg, artFallback, mutedBadge, ytHost);

    const nowBox = el("div", { class: "pb-now" });
    const pbTitle = el("div", { class: "pb-title idle", text: "Nothing spudding" });
    const pbArtist = el("div", { class: "pb-artist", text: "Queue up some music for the bunker" });
    nowBox.append(pbTitle, pbArtist);

    const range = el("input", {
      type: "range", min: "0", max: "100", step: "0.1", value: "0",
      "aria-label": "Playback position", disabled: true,
    });
    const curTime = el("span", { text: "0:00", "aria-hidden": "true" });
    const durTime = el("span", { text: "0:00", "aria-hidden": "true" });
    const progress = el("div", { class: "pb-progress" }, [curTime, range, durTime]);

    const shuffleBtn = el("button", { class: "btn-icon", title: "Shuffle", "aria-label": "Shuffle queue order", "aria-pressed": "false" }, [icon("shuffle", 17)]);
    const prevBtn = el("button", { class: "btn-icon", title: "Previous track", "aria-label": "Previous track" }, [icon("skipBack", 18)]);
    const playBtn = el("button", { class: "btn-icon play-btn", title: "Play", "aria-label": "Play or pause", disabled: true }, [icon("play", 18)]);
    const nextBtn = el("button", { class: "btn-icon", title: "Skip", "aria-label": "Skip to next track" }, [icon("skipFwd", 18)]);
    const repeatBtn = el("button", { class: "btn-icon", title: "Repeat off", "aria-label": "Cycle repeat mode", "aria-pressed": "false" }, [icon("repeat", 17)]);
    const controls = el("div", { class: "pb-controls" }, [shuffleBtn, prevBtn, playBtn, nextBtn, repeatBtn]);
    const permNote = el("span", { class: "pb-perm-note", hidden: true }, [icon("lock", 13), el("span", { text: "Owner has the aux" })]);

    const center = el("div", { class: "pb-center" }, [controls, progress, permNote]);

    const volRange = el("input", { type: "range", min: "0", max: "100", value: String(DEFAULT_VOLUME), "aria-label": "Music volume" });
    const volPct = el("span", { class: "vol-pct", text: `${DEFAULT_VOLUME}%`, "aria-hidden": "true" });
    const volBtn = el("button", { class: "btn-icon", title: "Mute music", "aria-label": "Mute music" }, [icon("volume", 17)]);
    const volumeWrap = el("div", { class: "volume-wrap" }, [volBtn, volRange, volPct]);

    const ytLinkBtn = el("button", {
      class: "btn-icon", title: "Open this track on YouTube", "aria-label": "Open this track on YouTube",
      disabled: true, onclick: () => this.openOnYouTube(),
    }, [icon("external", 17)]);

    const queueBtn = el("button", {
      class: "btn-icon queue-btn", title: "Queue", "aria-label": "Toggle the queue panel", "aria-expanded": "false",
    }, [icon("queue", 18), el("span", { class: "count", hidden: true })]);

    bar.append(
      el("div", { class: "pb-left" }, [addBtn, art]),
      nowBox,
      center,
      el("div", { class: "pb-side" }, [volumeWrap, ytLinkBtn, queueBtn]),
    );

    this.ui = {
      bar, art, artImg, artFallback, mutedBadge, ytHost, addBtn,
      pbTitle, pbArtist, range, curTime, durTime,
      shuffleBtn, prevBtn, playBtn, nextBtn, repeatBtn,
      permNote, volRange, volBtn, volPct, ytLinkBtn, queueBtn,
      controls, progress,
    };

    // wiring
    playBtn.addEventListener("click", () => {
      if (!this.state?.current) { this.send("play"); return; }
      this.send(this.state.playing ? "pause" : "resume");
    });
    nextBtn.addEventListener("click", () => this.send("skip"));
    prevBtn.addEventListener("click", () => this.send("prev"));
    shuffleBtn.addEventListener("click", () => this.send("shuffle", { on: !this.state?.shuffle }));
    repeatBtn.addEventListener("click", () => {
      const order = ["off", "all", "one"];
      const next = order[(order.indexOf(this.state?.repeat ?? "off") + 1) % 3];
      this.send("repeat", { mode: next });
    });
    queueBtn.addEventListener("click", () => setQueueOpen(shellRefs.queuePanel.hidden));

    range.addEventListener("pointerdown", () => { this.scrubbing = true; });
    const commitSeek = () => {
      if (!this.scrubbing) return;
      this.scrubbing = false;
      this.send("seek", { position: parseFloat(range.value) });
    };
    range.addEventListener("change", commitSeek);
    range.addEventListener("pointerup", commitSeek);
    range.addEventListener("keyup", () => this.send("seek", { position: parseFloat(range.value) }));
    range.addEventListener("input", () => {
      const val = parseFloat(range.value);
      this.ui.curTime.textContent = fmtDur(val);
      this.paintRangeFill(val);
    });

    volBtn.addEventListener("click", () => this.setVolume(undefined, !this.mutedLocal));
    volRange.addEventListener("input", () => this.setVolume(parseInt(volRange.value, 10), false));

    this.applyVolume();
    this.renderBar();
    this.startLoop();
    shellRefs.ytMount = ytHost.firstElementChild;
  }

  paintRangeFill(val) {
    const dur = this.duration();
    const pct = dur > 0 ? Math.max(0, Math.min(100, (val / dur) * 100)) : 0;
    this.ui.range.style.setProperty("--fill", pct + "%");
  }

  startLoop() {
    const step = () => {
      this.tickUI();
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }

  tickUI() {
    const st = this.state;
    const { range, curTime, durTime } = this.ui;
    if (this.scrubbing) return;
    if (st?.current) {
      const dur = this.duration();
      const pos = Math.min(this.expectedPosition(), dur || this.expectedPosition());
      range.disabled = !this.canControl || dur <= 0;
      range.max = String(dur > 0 ? dur : 100);
      range.value = String(pos);
      curTime.textContent = fmtDur(pos);
      durTime.textContent = fmtDur(dur);
      this.paintRangeFill(pos);
      let s = -1;
      try { s = this.ytReady ? this.yt.getPlayerState() : -1; } catch { }
      this.ui.bar.classList.toggle("buffering", st.playing && s === 3);
      this.driftCheck();
    } else {
      range.disabled = true;
      range.value = "0";
      curTime.textContent = "0:00";
      durTime.textContent = "0:00";
      this.paintRangeFill(0);
      this.ui.bar.classList.remove("buffering");
    }
  }

  renderBar() {
    const st = this.state;
    const u = this.ui;
    if (!u.bar) return;

    if (st?.current) {
      const t = st.current;
      u.artImg.hidden = false;
      u.artImg.src = t.artwork || `https://i.ytimg.com/vi/${t.videoId}/default.jpg`;
      u.artFallback.hidden = true;
      u.pbTitle.textContent = t.title;
      u.pbTitle.classList.remove("idle");
      u.pbArtist.textContent = t.artist || "unknown artist";
      u.playBtn.disabled = false;
      u.playBtn.replaceChildren(icon(st.playing ? "pause" : "play", 18));
      u.playBtn.title = st.playing ? "Pause" : "Play";
      u.shuffleBtn.classList.toggle("active", !!st.shuffle);
      u.shuffleBtn.setAttribute("aria-pressed", st.shuffle ? "true" : "false");
      u.repeatBtn.classList.toggle("active", st.repeat !== "off");
      u.repeatBtn.setAttribute("aria-pressed", st.repeat !== "off" ? "true" : "false");
      u.repeatBtn.replaceChildren(icon(st.repeat === "one" ? "repeatOne" : "repeat", 17));
      u.repeatBtn.title = st.repeat === "one" ? "Repeat one" : st.repeat === "all" ? "Repeat all" : "Repeat off";
      u.ytLinkBtn.disabled = false;
    } else {
      u.artImg.hidden = true;
      u.artFallback.hidden = false;
      u.pbTitle.textContent = "Nothing spudding";
      u.pbTitle.classList.add("idle");
      u.pbArtist.textContent = this.roomId ? "Nothing queued — add some music" : "Join a bunker to start the jam";
      u.playBtn.disabled = true;
      u.playBtn.replaceChildren(icon("play", 18));
      u.shuffleBtn.classList.remove("active");
      u.repeatBtn.classList.remove("active");
      u.ytLinkBtn.disabled = true;
    }

    const can = this.canControl && this.roomId;
    u.nextBtn.disabled = !can;
    u.prevBtn.disabled = !can;
    u.shuffleBtn.disabled = !can;
    u.repeatBtn.disabled = !can;
    u.addBtn.disabled = !this.roomId;
    u.permNote.hidden = can || !this.roomId;

    const count = u.queueBtn.querySelector(".count");
    count.hidden = !this.queue.length;
    count.textContent = this.queue.length > 99 ? "99+" : String(this.queue.length);
    u.queueBtn.setAttribute("aria-expanded", String(!shellRefs.queuePanel.hidden));
  }

  renderVolume() {
    const u = this.ui;
    if (!u.volRange) return;
    const shown = this.mutedLocal ? 0 : this.volume;
    u.volRange.value = String(this.volume);
    u.volPct.textContent = `${shown}%`;
    u.volBtn.replaceChildren(icon(this.mutedLocal || this.volume === 0 ? "volumeX" : "volume", 17));
    u.volBtn.title = this.mutedLocal ? "Unmute music" : "Mute music";
    // obvious "why is it quiet" badge on the artwork
    if (u.mutedBadge) u.mutedBadge.hidden = !(this.mutedLocal || this.volume === 0);
  }
}

export const player = new PotatoPlayer();

on("bootstrap", () => player.updatePerm());
