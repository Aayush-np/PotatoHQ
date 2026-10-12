/* PotatoHQ icon set — hand-drawn 24px stroke icons. SVG content is static/trusted. */

const P = {
  potato: `<path d="M12 3.2c4.5 0 7.8 2.8 7.7 6.6-.1 3.9-3 7-7.5 7-4.4 0-7.9-2.9-7.9-6.8C4.3 6 7.6 3.2 12 3.2Z" fill="currentColor" stroke="none"/><path d="M8.2 9.1c.4-.5 1-.5 1.3 0M14 9.1c.4-.5 1-.5 1.3 0M9.8 12.4c1.2 1 3.2 1 4.4 0" stroke="var(--bg0)" stroke-width="1.3" fill="none" stroke-linecap="round"/>`,
  users: `<path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M21 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>`,
  message: `<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>`,
  room: `<path d="M3 21V8l9-5 9 5v13"/><path d="M9 21v-6h6v6"/><path d="M3 21h18"/>`,
  plus: `<path d="M12 5v14M5 12h14"/>`,
  search: `<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>`,
  mic: `<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><path d="M12 18v4"/>`,
  micOff: `<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><path d="m3 3 18 18"/>`,
  headset: `<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="7" rx="2"/><rect x="17" y="14" width="4" height="7" rx="2"/>`,
  play: `<path d="M7 4.5v15l12-7.5Z" fill="currentColor" stroke="none"/>`,
  pause: `<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/>`,
  skipBack: `<path d="M18 5v14l-9-7Z" fill="currentColor" stroke="none"/><rect x="4" y="5" width="2.4" height="14" rx="1" fill="currentColor" stroke="none"/>`,
  skipFwd: `<path d="M6 5v14l9-7Z" fill="currentColor" stroke="none"/><rect x="17.6" y="5" width="2.4" height="14" rx="1" fill="currentColor" stroke="none"/>`,
  shuffle: `<path d="M3 5h3.5c5.5 0 8.5 14 14 14H22"/><path d="M3 19h3.5c2.2 0 3.9-2 5.2-4.4"/><path d="M14.8 9.4C16.1 7 17.8 5 20.2 5H22"/><path d="m18 2 4 3-4 3M18 16l4 3-4 3"/>`,
  repeat: `<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>`,
  repeatOne: `<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10.2 12.6 9.3V15"/>`,
  queue: `<path d="M3 6h11"/><path d="M3 12h11"/><path d="M3 18h7"/><path d="m16 12 5 4-5 4"/>`,
  volume: `<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9.5 9.5 0 0 1 0 13"/>`,
  volumeX: `<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="m16 9 6 6M22 9l-6 6"/>`,
  x: `<path d="M18 6 6 18M6 6l12 12"/>`,
  check: `<path d="M20 6 9 17l-5-5"/>`,
  send: `<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>`,
  smile: `<circle cx="12" cy="12" r="9"/><path d="M8 14c1 1.3 2.4 2 4 2s3-.7 4-2"/><path d="M9 9h.01M15 9h.01" stroke-linecap="round" stroke-width="2.4"/>`,
  reply: `<path d="m9 17-5-5 5-5"/><path d="M4 12h11a6 6 0 0 1 6 6v3"/>`,
  pencil: `<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>`,
  trash: `<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/>`,
  copy: `<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>`,
  settings: `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1Z"/>`,
  crown: `<path d="m2 6 4.5 4L12 4l5.5 6L22 6l-1.6 13a2 2 0 0 1-2 1.7H5.6a2 2 0 0 1-2-1.7Z"/>`,
  exit: `<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>`,
  wifi: `<path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 15.5a5.5 5.5 0 0 1 7 0"/><path d="M12 19h.01" stroke-linecap="round" stroke-width="2.6"/>`,
  wifiOff: `<path d="m2 2 20 20M8.5 15.5a5.5 5.5 0 0 1 7 0M5 12.5a10 10 0 0 1 5-2.6"/><path d="M12 19h.01" stroke-linecap="round" stroke-width="2.6"/>`,
  dots: `<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>`,
  music: `<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>`,
  userPlus: `<path d="M15 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>`,
  userCheck: `<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="m16 11 2 2 4-4"/>`,
  userX: `<path d="M15 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="m17 8 5 5M22 8l-5 5"/>`,
  chevronDown: `<path d="m6 9 6 6 6-6"/>`,
  chevronLeft: `<path d="m15 18-6-6 6-6"/>`,
  chevronRight: `<path d="m9 18 6-6-6-6"/>`,
  menu: `<path d="M3 6h18M3 12h18M3 18h18"/>`,
  lock: `<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>`,
  hand: `<path d="M7.5 11.5V6.2a1.4 1.4 0 0 1 2.8 0V11"/><path d="M10.3 11V4.9a1.4 1.4 0 0 1 2.8 0V11"/><path d="M13.1 11V6.2a1.4 1.4 0 0 1 2.8 0V13a7 7 0 0 1-7 7 6.4 6.4 0 0 1-5.3-2.8l-1.8-2.7c-.6-1 .1-2.3 1.3-2.3.5 0 1 .3 1.3.7l1.6 2"/>`,
  keyboard: `<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 14h6"/>`,
  external: `<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>`,
  sliders: `<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1.5 14h5M9.5 8h5M17.5 16h5"/>`,
  refresh: `<path d="M21 12a9 9 0 1 1-2.6-6.3"/><path d="M21 3v6h-6"/>`,
  image: `<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>`,
  info: `<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01" stroke-linecap="round" stroke-width="2.4"/>`,
};

export function icon(name, size = 18, cls = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  if (cls) svg.setAttribute("class", cls);
  svg.innerHTML = P[name] || P.info;
  return svg;
}

export const LOGO_POTATO = `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M50 12 C72 12 88 30 87 53 C86 77 70 92 49 92 C28 92 13 76 13 52 C13 29 28 12 50 12 Z" fill="#C9973B"/>
  <ellipse cx="30" cy="66" rx="6" ry="4" fill="#00000026" transform="rotate(-14 30 66)"/>
  <ellipse cx="70" cy="38" rx="5" ry="3.4" fill="#00000026" transform="rotate(18 70 38)"/>
  <path d="M27 48 C27 28 73 28 73 48" stroke="#241C0B" stroke-width="5" fill="none" stroke-linecap="round"/>
  <rect x="20" y="44" width="9" height="15" rx="4.5" fill="#241C0B"/>
  <rect x="71" y="44" width="9" height="15" rx="4.5" fill="#241C0B"/>
  <circle cx="42" cy="58" r="3.4" fill="#241C0B"/>
  <circle cx="58" cy="58" r="3.4" fill="#241C0B"/>
  <path d="M42 69 Q50 75.5 58 69" stroke="#241C0B" stroke-width="3" fill="none" stroke-linecap="round"/>
</svg>`;
