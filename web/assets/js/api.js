/* REST client. Same-origin cookies; custom header doubles as CSRF guard. */

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || "Something went sideways.");
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body, isForm) {
  const opts = {
    method,
    headers: { "X-Potato": "1" },
    credentials: "same-origin",
  };
  if (body !== undefined && !isForm) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (isForm) {
    opts.body = body;
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const detail = data && (data.detail || data.message) || `Request failed (${res.status})`;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  patch: (p, b) => request("PATCH", p, b ?? {}),
  delete: (p, b) => request("DELETE", p, b),
  upload: (p, formData) => request("POST", p, formData, true),

  register: (email, username, password, displayName) =>
    request("POST", "/api/auth/register", { email, username, password, displayName }),
  login: (email, password) => request("POST", "/api/auth/login", { email, password }),
  logout: () => request("POST", "/api/auth/logout", {}),
  me: () => request("GET", "/api/me"),
  updateMe: (patch) => request("PATCH", "/api/me", patch),
  uploadAvatar: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("POST", "/api/me/avatar", fd, true);
  },
  getUser: (id) => request("GET", `/api/users/${id}`),

  bootstrap: () => request("GET", "/api/bootstrap"),

  addFriend: (query) => request("POST", "/api/friends/requests", { query }),
  acceptFriend: (id) => request("POST", `/api/friends/requests/${id}/accept`, {}),
  declineFriend: (id) => request("POST", `/api/friends/requests/${id}/decline`, {}),
  cancelFriend: (id) => request("DELETE", `/api/friends/requests/${id}`),
  removeFriend: (id) => request("DELETE", `/api/friends/${id}`),

  createRoom: (name, topic, inviteUserIds) =>
    request("POST", "/api/rooms", { name, topic, inviteUserIds }),
  roomDetail: (id) => request("GET", `/api/rooms/${id}`),
  joinByCode: (code) => request("POST", "/api/rooms/join", { code }),
  inviteToRoom: (roomId, userIds) => request("POST", `/api/rooms/${roomId}/invite`, { userIds }),
  acceptInvite: (roomId) => request("POST", `/api/rooms/${roomId}/invites/accept`, {}),
  declineInvite: (roomId) => request("POST", `/api/rooms/${roomId}/invites/decline`, {}),
  leaveRoom: (roomId) => request("POST", `/api/rooms/${roomId}/leave`, {}),
  deleteRoom: (roomId) => request("DELETE", `/api/rooms/${roomId}`),
  kickMember: (roomId, userId) => request("POST", `/api/rooms/${roomId}/kick`, { userId }),
  updateRoom: (roomId, patch) => request("PATCH", `/api/rooms/${roomId}`, patch),
  openDm: (userId) => request("POST", "/api/dm", { userId }),
  messages: (roomId, before = 0, limit = 50) =>
    request("GET", `/api/rooms/${roomId}/messages?before=${before}&limit=${limit}`),

  musicSearch: (q, filter, limit = 20) =>
    request("GET", `/api/music/search?q=${encodeURIComponent(q)}&filter=${filter}&limit=${limit}`),
  musicRelated: (videoId) => request("GET", `/api/music/related/${videoId}`),
  musicAlbum: (id) => request("GET", `/api/music/album/${encodeURIComponent(id)}`),
  musicPlaylist: (id) => request("GET", `/api/music/playlist/${encodeURIComponent(id)}`),
  musicArtist: (id) => request("GET", `/api/music/artist/${encodeURIComponent(id)}`),
  musicState: (roomId) => request("GET", `/api/music/state/${roomId}`),
};
