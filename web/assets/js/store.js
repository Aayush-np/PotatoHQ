/* Application state + a tiny pub/sub. All mutation goes through store.set/emit. */

const listeners = new Map();

export const store = {
  me: null,
  friends: [],
  requestsIn: [],
  requestsOut: [],
  rooms: [],
  invites: [],
  dms: [],
  unread: {},
  wsConnected: false,
  pendingJoinCode: null,

  // the currently open channel
  channel: null,
  /* channel: {
    id, kind: 'room'|'dm', room, members, messages: [], messageMap: Map,
    typing: Map(userId -> {name, until}), hasMore, loadingOlder,
    voice: {participants: []}, inVoice: false, voiceMuted: false, voiceListener: false,
  } */

  // global music binding (player bar)
  musicRoomId: null,
};

export function on(topic, fn) {
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic).add(fn);
  return () => listeners.get(topic)?.delete(fn);
}

export function emit(topic, data) {
  listeners.get(topic)?.forEach((fn) => {
    try { fn(data); } catch (e) { console.error(`[store] listener error on ${topic}`, e); }
  });
}

export function applyBootstrap(b) {
  store.me = b.user;
  store.friends = b.friends || [];
  store.requestsIn = b.requestsIn || [];
  store.requestsOut = b.requestsOut || [];
  store.rooms = b.rooms || [];
  store.invites = b.invites || [];
  store.dms = b.dms || [];
  store.unread = b.unread || {};
  emit("bootstrap");
  emit("sidebar");
}

export function setUnread(roomId, count) {
  store.unread[roomIdId(roomId)] = count;
  emit("sidebar");
}

export function unreadTotal() {
  let n = 0;
  for (const k of Object.keys(store.unread)) n += store.unread[k] || 0;
  return n;
}

function roomIdId(x) { return String(x); }

export function findRoom(id) {
  return store.rooms.find((r) => r.id === id);
}

export function findDm(roomId) {
  return store.dms.find((d) => d.roomId === roomId);
}

export function findFriendByRoom(roomId) {
  const dm = findDm(roomId);
  return dm ? dm.user : null;
}

export function isFriend(userId) {
  return store.friends.some((f) => f.id === userId);
}

export function setPresence(card) {
  // presence events carry a full user card
  const friend = store.friends.find((f) => f.id === card.id);
  if (friend) {
    friend.online = card.online;
    friend.activity = card.activity || null;
    emit("sidebar");
  }
  const dm = store.dms.find((d) => d.user.id === card.id);
  if (dm) {
    dm.user.online = card.online;
    dm.user.activity = card.activity || null;
    emit("sidebar");
  }
  if (store.channel) {
    const member = store.channel.members.find((m) => m.id === card.id);
    if (member) {
      member.online = card.online;
      member.activity = card.activity || null;
      emit("members");
    }
  }
  emit("presence", card);
}

export function bumpRoomLiveness(roomId, patch) {
  const room = findRoom(roomId);
  if (room) {
    room.live = { ...(room.live || { music: false, voice: 0 }), ...patch };
    emit("sidebar");
  }
}
