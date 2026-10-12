/* Voice chat: WebRTC mesh with server-side signaling relay.

Features:
- New joiner initiates offers to everyone already in voice (glare-safe).
- Remote audio routed through a Web Audio graph → per-peer volume (0-200%),
  local deafen (all audio muted), and output-device selection.
- Speaking detection via analysers on the same graph.
- Push-to-talk (hold V), raise hand, listen-only fallback when no mic exists.
- Device management: hot-swap microphone via replaceTrack (no renegotiation).
*/

import { wsSend, onWs } from "./ws.js";
import { emit } from "./store.js";

const SPEAKING_THRESHOLD = 0.045;
const HANGOVER_MS = 420;

const LS = {
  vol: (uid) => `potato-vol-${uid}`,
  input: "potato-audio-input",
  output: "potato-audio-output",
  echo: "potato-audio-echo",
  noise: "potato-audio-noise",
  ptt: "potato-audio-ptt",
};

let _iceServers = null;
async function iceServers() {
  if (_iceServers) return _iceServers;
  const base = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }];
  try {
    const res = await fetch("/api/rtc/config", { credentials: "same-origin", headers: { "X-Potato": "1" } });
    const data = await res.json();
    if (Array.isArray(data.iceServers) && data.iceServers.length) {
      _iceServers = data.iceServers;
      return _iceServers;
    }
  } catch { /* offline: STUN only */ }
  _iceServers = base;
  return _iceServers;
}

class VoiceEngine {
  constructor() {
    this.roomId = null;
    this.localStream = null;
    this.listenerOnly = false;
    this.muted = false;
    this.deafened = false;
    this.raised = false;
    this.pttEnabled = localStorage.getItem(LS.ptt) === "1";
    this.audioCtx = null;
    this.peers = new Map(); // userId -> {pc, stream, gain, analyser, speaking, hangover, volume}
    this.ownAnalyser = null;
    this.ownSpeaking = false;
    this.ownHangover = 0;
    this.participants = []; // server roster view
    this.detectTimer = null;
    this.status = "idle"; // idle | connecting | connected
    this._micTest = null; // {stream, analyser, onLevel}
    this._reset();
    this._bindPTT();
  }

  _reset() {
    this.closeAllPeers();
    if (this.localStream) {
      this.localStream.getTracks().forEach((t) => t.stop());
      this.localStream = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      try { this.audioCtx.close(); } catch { /* ignore */ }
    }
    this.audioCtx = null;
    this.ownAnalyser = null;
    this.ownSpeaking = false;
    if (this.detectTimer) { clearInterval(this.detectTimer); this.detectTimer = null; }
    this.status = "idle";
    emit("voice");
  }

  get inVoice() { return this.roomId !== null; }

  /* ---------- settings ---------- */

  get inputDeviceId() { return localStorage.getItem(LS.input) || undefined; }
  set inputDeviceId(id) { id ? localStorage.setItem(LS.input, id) : localStorage.removeItem(LS.input); }
  get outputDeviceId() { return localStorage.getItem(LS.output) || undefined; }
  set outputDeviceId(id) { id ? localStorage.setItem(LS.output, id) : localStorage.removeItem(LS.output); }
  get echoCancellation() { return localStorage.getItem(LS.echo) !== "0"; }
  set echoCancellation(v) { localStorage.setItem(LS.echo, v ? "1" : "0"); }
  get noiseSuppression() { return localStorage.getItem(LS.noise) !== "0"; }
  set noiseSuppression(v) { localStorage.setItem(LS.noise, v ? "1" : "0"); }

  async listAudioDevices() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      return {
        inputs: devices.filter((d) => d.kind === "audioinput"),
        outputs: devices.filter((d) => d.kind === "audiooutput"),
        granted: devices.some((d) => d.label),
      };
    } catch { return { inputs: [], outputs: [], granted: false }; }
  }

  async ensureMicPermission() {
    if (this.localStream) return true;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach((t) => t.stop());
      return true;
    } catch { return false; }
  }

  _micConstraints() {
    const c = { echoCancellation: this.echoCancellation, noiseSuppression: this.noiseSuppression, autoGainControl: true };
    if (this.inputDeviceId) c.deviceId = { exact: this.inputDeviceId };
    return { audio: c };
  }

  /* ---------- mic test (settings modal) ---------- */

  async startMicTest(onLevel) {
    this.stopMicTest();
    try {
      const stream = await navigator.mediaDevices.getUserMedia(this._micConstraints());
      const ctx = this.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      this.audioCtx = this.audioCtx || ctx;
      if (ctx.state === "suspended") await ctx.resume().catch(() => {});
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      this._micTest = { stream, analyser, onLevel };
      return true;
    } catch { return false; }
  }

  stopMicTest() {
    if (!this._micTest) return;
    this._micTest.stream.getTracks().forEach((t) => t.stop());
    this._micTest = null;
  }

  micTestLevel() {
    if (!this._micTest) return 0;
    return this.rms(this._micTest.analyser);
  }

  /* ---------- join / leave ---------- */

  async join(roomId) {
    if (this.roomId === roomId) return;
    if (this.roomId) this.leave();
    this.roomId = roomId;
    this.status = "connecting";
    this.listenerOnly = false;
    this.raised = false;
    emit("voice");

    try {
      this.localStream = await navigator.mediaDevices.getUserMedia(this._micConstraints());
      this.localStream.getAudioTracks().forEach((t) => { t.enabled = !this.muted; });
    } catch (e) {
      this.listenerOnly = true;
      this.muted = false;
    }

    try {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (this.audioCtx.state === "suspended") {
        await this.audioCtx.resume().catch(() => {});
        // some browsers only resume after a gesture; retry on the next tap
        const resume = () => { this.audioCtx?.resume().catch(() => {}); document.removeEventListener("pointerdown", resume); };
        document.addEventListener("pointerdown", resume, { once: true });
      }
      if (this.outputDeviceId) this.applyOutputDevice();
      if (this.localStream) this.ownAnalyser = this.makeAnalyser(this.localStream);
    } catch { /* graph optional for listen-only edge cases */ }

    this.iceServers = await iceServers();
    wsSend({ type: "voice.join", roomId, muted: this.muted || (this.pttEnabled && this.localStream), listener: this.listenerOnly });
    if (this.deafened) wsSend({ type: "voice.deafen", deafened: true });
    this.startDetection();
  }

  leave() {
    if (!this.roomId) return;
    const rid = this.roomId;
    this.roomId = null;
    wsSend({ type: "voice.leave", roomId: rid });
    if (this.raised) { this.raised = false; }
    this.participants = [];
    this._reset();
  }

  /* ---------- mute / deafen / hand / PTT ---------- */

  setMuted(muted, { silent = false } = {}) {
    this.muted = !!muted;
    if (this.localStream) {
      this.localStream.getAudioTracks().forEach((t) => { t.enabled = !this.muted; });
    }
    if (this.roomId && !silent) wsSend({ type: "voice.mute", muted: this.muted });
    if (this.muted) this._setOwnSpeaking(false);
    emit("voice");
  }

  setDeafened(deafened) {
    this.deafened = !!deafened;
    if (this.deafened) {
      // deafening also mutes your mic (you can't hear anyone; don't broadcast into the void)
      this.setMuted(true);
    } else if (this.localStream && this.pttEnabled) {
      this.setMuted(true); // PTT keeps you muted until you hold V
    } else {
      this.setMuted(false);
    }
    if (this.roomId) wsSend({ type: "voice.deafen", deafened: this.deafened });
    for (const [uid, peer] of this.peers) this.applyPeerVolume(uid, peer);
    emit("voice");
  }

  setRaised(raised) {
    this.raised = !!raised;
    if (this.roomId) wsSend({ type: "voice.hand", raised: this.raised });
    emit("voice");
  }

  setPttEnabled(on) {
    this.pttEnabled = !!on;
    localStorage.setItem(LS.ptt, on ? "1" : "0");
    if (this.pttEnabled && this.inVoice) this.setMuted(true);
    if (!this.pttEnabled && this.inVoice && !this.deafened) this.setMuted(false);
    emit("voice");
  }

  _bindPTT() {
    document.addEventListener("keydown", (e) => {
      if (!this.pttEnabled || !this.inVoice || this.listenerOnly || this.deafened) return;
      if (e.repeat || e.key !== "v" && e.key !== "V") return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      this.setMuted(false);
    });
    document.addEventListener("keyup", (e) => {
      if (!this.pttEnabled || !this.inVoice || this.listenerOnly) return;
      if (e.key !== "v" && e.key !== "V") return;
      this.setMuted(true);
    });
  }

  /* ---------- device hot-swap ---------- */

  async switchInputDevice(deviceId) {
    this.inputDeviceId = deviceId || undefined;
    if (!this.inVoice || this.listenerOnly) return true;
    try {
      const fresh = await navigator.mediaDevices.getUserMedia(this._micConstraints());
      const newTrack = fresh.getAudioTracks()[0];
      if (!newTrack) return false;
      newTrack.enabled = !this.muted;
      for (const peer of this.peers.values()) {
        const sender = peer.pc.getSenders().find((s) => s.track && s.track.kind === "audio");
        if (sender) await sender.replaceTrack(newTrack);
      }
      this.localStream.getTracks().forEach((t) => t.stop());
      this.localStream = fresh;
      if (this.audioCtx) {
        try { this.ownAnalyser = this.makeAnalyser(fresh); } catch { /* keep old */ }
      }
      return true;
    } catch { return false; }
  }

  async applyOutputDevice() {
    const id = this.outputDeviceId;
    if (!id || !this.audioCtx) return;
    try {
      if (typeof this.audioCtx.setSinkId === "function") {
        await this.audioCtx.setSinkId(id);
      }
    } catch { /* unsupported (Safari/Firefox) — voices stay on the default device */ }
  }

  async setOutputDevice(deviceId) {
    this.outputDeviceId = deviceId || undefined;
    await this.applyOutputDevice();
  }

  /* ---------- per-peer volume ---------- */

  peerVolume(uid) {
    const v = parseFloat(localStorage.getItem(LS.vol(uid)));
    return isFinite(v) ? Math.max(0, Math.min(2, v)) : 1;
  }

  setPeerVolume(uid, value) {
    const v = Math.max(0, Math.min(2, value));
    localStorage.setItem(LS.vol(uid), String(v));
    const peer = this.peers.get(uid);
    if (peer) this.applyPeerVolume(uid, peer);
    emit("voice");
  }

  applyPeerVolume(uid, peer) {
    if (!peer.gain) return;
    peer.gain.gain.value = this.deafened ? 0 : this.peerVolume(uid);
  }

  /* ---------- roster + peers ---------- */

  handleVoiceState(data) {
    if (this.roomId !== data.roomId) return;
    this.participants = data.participants || [];
    if (this.status !== "connected") this.status = "connected";
    const roster = new Set(this.participants.map((p) => p.user.id));
    roster.delete(ownUserId());

    for (const [uid, peer] of this.peers) {
      if (!roster.has(uid)) this.closePeer(uid);
    }
    // Deterministic direction: the lower user id always initiates the offer.
    // No glare, no SDP rollback (Chrome's ICE gathering can stall after a
    // rolled-back offer — with one-sided offers that path never happens).
    for (const uid of roster) {
      if (!this.peers.has(uid) && ownUserId() < uid) this.initiateOffer(uid);
    }
    emit("voice");
  }

  handleSpeaking(data) {
    if (data.roomId !== this.roomId) return;
    const p = this.participants.find((x) => x.user.id === data.userId);
    if (p) { p.speaking = data.speaking; emit("voice"); }
  }

  async initiateOffer(peerId) {
    const pc = this.createPeer(peerId);
    if (this.localStream) {
      for (const track of this.localStream.getTracks()) pc.addTrack(track, this.localStream);
    } else {
      pc.addTransceiver("audio", { direction: "recvonly" });
    }
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    wsSend({ type: "rtc.offer", to: peerId, sdp: offer.sdp });
  }

  createPeer(peerId) {
    const engine = this;
    const pc = new RTCPeerConnection({
      iceServers: this.iceServers || [{ urls: ["stun:stun.l.google.com:19302"] }],
    });
    const peer = { pc, stream: null, gain: null, analyser: null, speaking: false, hangover: 0 };
    this.peers.set(peerId, peer);
    pc.onicecandidate = (e) => {
      if (e.candidate) wsSend({ type: "rtc.ice", to: peerId, candidate: e.candidate });
    };
    pc.ontrack = (e) => {
      peer.stream = e.streams[0];
      engine.attachRemote(peerId, peer);
    };
    pc.onconnectionstatechange = () => {
      if (["failed", "closed"].includes(pc.connectionState)) this.closePeer(peerId);
    };
    return pc;
  }

  attachRemote(peerId, peer) {
    if (!this.audioCtx) return; // graph missing — nothing to do (shouldn't happen post-join)
    if (peer.gain) return;
    try {
      const src = this.audioCtx.createMediaStreamSource(peer.stream);
      const gain = this.audioCtx.createGain();
      const analyser = this.audioCtx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(gain);
      gain.connect(analyser);
      analyser.connect(this.audioCtx.destination); // hear each other here
      peer.gain = gain;
      peer.analyser = analyser;
      this.applyPeerVolume(peerId, peer);
    } catch (e) {
      console.warn("[voice] audio graph failed, falling back to <audio>", e);
      const audio = new Audio();
      audio.srcObject = peer.stream;
      audio.volume = this.deafened ? 0 : this.peerVolume(peerId);
      audio.play().catch(() => { /* resumes on next gesture */ });
      peer.audioEl = audio;
    }
  }

  makeAnalyser(stream) {
    const src = this.audioCtx.createMediaStreamSource(stream);
    const an = this.audioCtx.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    return an;
  }

  handleRtc(type, data) {
    if (data.roomId !== this.roomId) return;
    const from = data.from;
    if (type === "offer") {
      let peer = this.peers.get(from);
      if (peer) {
        if (peer.pc.signalingState === "have-local-offer") {
          if (ownUserId() > from) return; // impolite side keeps its own offer
        } else if (peer.pc.signalingState !== "stable") return;
      }
      const pc = peer ? peer.pc : this.createPeer(from);
      pc.setRemoteDescription({ type: "offer", sdp: data.sdp }).then(async () => {
        if (this.localStream && !pc.getSenders().length) {
          for (const track of this.localStream.getTracks()) pc.addTrack(track, this.localStream);
        }
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        wsSend({ type: "rtc.answer", to: from, sdp: answer.sdp });
      }).catch((e) => console.warn("[voice] answer failed", e));
    } else if (type === "answer") {
      const peer = this.peers.get(from);
      if (peer && peer.pc.signalingState === "have-local-offer") {
        peer.pc.setRemoteDescription({ type: "answer", sdp: data.sdp }).catch(() => { });
      }
    } else if (type === "ice") {
      const peer = this.peers.get(from);
      if (peer && data.candidate) {
        peer.pc.addIceCandidate(data.candidate).catch(() => { });
      }
    }
  }

  closePeer(peerId) {
    const peer = this.peers.get(peerId);
    if (!peer) return;
    try { peer.pc.close(); } catch { /* ignore */ }
    if (peer.audioEl) { peer.audioEl.srcObject = null; peer.audioEl.remove(); }
    this.peers.delete(peerId);
    emit("voice");
  }

  closeAllPeers() {
    for (const uid of [...this.peers.keys()]) this.closePeer(uid);
  }

  /* ---------- speaking detection ---------- */

  rms(analyser) {
    if (!analyser) return 0;
    const buf = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    return Math.sqrt(sum / buf.length);
  }

  startDetection() {
    if (this.detectTimer) return;
    this.detectTimer = setInterval(() => {
      const now = performance.now();
      if (this._micTest) {
        this._micTest.onLevel?.(this.rms(this._micTest.analyser));
      }
      if (this.localStream && !this.muted && this.ownAnalyser) {
        const level = this.rms(this.ownAnalyser);
        if (level > SPEAKING_THRESHOLD) {
          this.ownHangover = now + HANGOVER_MS;
          this._setOwnSpeaking(true);
        } else if (this.ownSpeaking && now > this.ownHangover) {
          this._setOwnSpeaking(false);
        }
      }
      for (const [uid, peer] of this.peers) {
        if (!peer.analyser) continue;
        const level = this.rms(peer.analyser);
        if (level > SPEAKING_THRESHOLD) {
          peer.hangover = now + HANGOVER_MS;
          this._setPeerSpeaking(uid, peer, true);
        } else if (peer.speaking && now > peer.hangover) {
          this._setPeerSpeaking(uid, peer, false);
        }
      }
    }, 160);
  }

  _setOwnSpeaking(v) {
    if (this.ownSpeaking === v) return;
    this.ownSpeaking = v;
    if (this.roomId) wsSend({ type: "voice.speaking", speaking: v });
    emit("voice");
  }

  _setPeerSpeaking(uid, peer, v) {
    if (peer.speaking === v) return;
    peer.speaking = v;
    const p = this.participants.find((x) => x.user.id === uid);
    if (p) p.speaking = v;
    emit("voice");
  }

  rejoinAfterReconnect() {
    if (this.roomId) {
      wsSend({ type: "voice.join", roomId: this.roomId, muted: this.muted, listener: this.listenerOnly });
      if (this.deafened) wsSend({ type: "voice.deafen", deafened: true });
      if (this.raised) wsSend({ type: "voice.hand", raised: true });
    }
  }
}

let _me = () => 0;
export function setOwnIdProvider(fn) { _me = fn; }
function ownUserId() { return _me(); }

export const voice = new VoiceEngine();

onWs("voice.state", (d) => voice.handleVoiceState(d));
onWs("voice.speaking", (d) => voice.handleSpeaking(d));
onWs("rtc.offer", (d) => voice.handleRtc("offer", d));
onWs("rtc.answer", (d) => voice.handleRtc("answer", d));
onWs("rtc.ice", (d) => voice.handleRtc("ice", d));
