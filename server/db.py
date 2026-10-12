"""SQLite persistence layer. WAL mode, dict rows, tiny helpers."""
import sqlite3
import threading

from .config import DB_PATH

_local = threading.local()


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        c.isolation_level = None  # autocommit; explicit BEGIN not needed at this scale
        _local.conn = c
    return c


def all(sql: str, *params) -> list[dict]:
    cur = _conn().execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def one(sql: str, *params):
    cur = _conn().execute(sql, params)
    r = cur.fetchone()
    return dict(r) if r else None


def run(sql: str, *params) -> sqlite3.Cursor:
    return _conn().execute(sql, params)


def insert(sql: str, *params) -> int:
    cur = _conn().execute(sql, params)
    return cur.lastrowid


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  avatar_path TEXT,
  created_at REAL NOT NULL,
  last_seen REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS friendships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,       -- requester
  friend_id INTEGER NOT NULL,     -- recipient
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted
  created_at REAL NOT NULL,
  UNIQUE(user_id, friend_id)
);

CREATE TABLE IF NOT EXISTS rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  topic TEXT NOT NULL DEFAULT '',
  owner_id INTEGER NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'room',        -- room | dm
  music_mode TEXT NOT NULL DEFAULT 'shared', -- owner | shared
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
  room_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',   -- owner | member
  status TEXT NOT NULL DEFAULT 'active',-- active | invited
  joined_at REAL NOT NULL,
  last_read_id INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (room_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_members_user ON members(user_id);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER NOT NULL,
  user_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'text',   -- text | system
  content TEXT NOT NULL,
  reply_to INTEGER,
  created_at REAL NOT NULL,
  edited_at REAL,
  deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);

CREATE TABLE IF NOT EXISTS reactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  emoji TEXT NOT NULL,
  UNIQUE(message_id, user_id, emoji)
);

CREATE TABLE IF NOT EXISTS playback (
  room_id INTEGER PRIMARY KEY,
  video_id TEXT,
  title TEXT, artist TEXT, artwork TEXT,
  duration REAL,
  position REAL NOT NULL DEFAULT 0,
  playing INTEGER NOT NULL DEFAULT 0,
  anchor REAL NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 0,
  repeat TEXT NOT NULL DEFAULT 'off',
  shuffle INTEGER NOT NULL DEFAULT 0,
  autoplay INTEGER NOT NULL DEFAULT 1,
  updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS queue_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER NOT NULL,
  video_id TEXT NOT NULL,
  title TEXT NOT NULL,
  artist TEXT NOT NULL DEFAULT '',
  artwork TEXT,
  duration REAL,
  added_by INTEGER NOT NULL,
  position REAL NOT NULL,
  added_at REAL NOT NULL,
  played_at REAL
);
CREATE INDEX IF NOT EXISTS idx_queue_room ON queue_items(room_id, position);
CREATE INDEX IF NOT EXISTS idx_queue_played ON queue_items(room_id, played_at);
"""


def init() -> None:
    c = _conn()
    c.executescript(SCHEMA)
