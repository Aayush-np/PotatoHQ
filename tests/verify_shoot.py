import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect("data/potatohq.db")
c.row_factory = sqlite3.Row
rid = c.execute("SELECT MAX(id) FROM rooms").fetchone()[0]
row = c.execute("SELECT video_id, title, artist, playing FROM playback WHERE room_id=?", (rid,)).fetchone()
print("now playing:", dict(row) if row else None)
sys_msgs = c.execute(
    "SELECT content FROM messages WHERE room_id=? AND kind='system' ORDER BY id DESC LIMIT 5",
    (rid,),
).fetchall()
print("system messages:", [m["content"][:60] for m in sys_msgs] or "NONE - chat is clean")
q = c.execute(
    "SELECT title, artist FROM queue_items WHERE room_id=? AND played_at IS NULL ORDER BY position",
    (rid,),
).fetchall()
print("queue:", [(m["title"], m["artist"]) for m in q])
