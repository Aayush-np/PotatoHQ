"""PotatoHQ server configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
AVATARS_DIR = UPLOADS_DIR / "avatars"
WEB_DIR = BASE_DIR / "web"
DB_PATH = DATA_DIR / "potatohq.db"

for _d in (DATA_DIR, UPLOADS_DIR, AVATARS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Networking — set these to run PotatoHQ for your whole friend group:
#   POTATO_HOST=0.0.0.0  POTATO_PORT=8420      LAN / VPS binding
#   POTATO_SECURE_COOKIES=1                     behind HTTPS (required for wss + secure cookies)
#   POTATO_TURN_URL / _USER / _CRED            TURN relay so voice works across strict NATs
HOST = os.getenv("POTATO_HOST", "0.0.0.0")
PORT = int(os.getenv("POTATO_PORT", "8420"))
COOKIE_SECURE = os.getenv("POTATO_SECURE_COOKIES", "").lower() in ("1", "true", "yes")
TURN_URL = os.getenv("POTATO_TURN_URL", "").strip()
TURN_USER = os.getenv("POTATO_TURN_USER", "").strip()
TURN_CRED = os.getenv("POTATO_TURN_CRED", "").strip()

SESSION_COOKIE = "potato_session"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days

# Input limits
MAX_MESSAGE_LEN = 4000
MAX_NAME_LEN = 60
MAX_TOPIC_LEN = 140
MAX_DISPLAY_LEN = 40
MAX_QUEUE_ITEMS = 200
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# Voice / WebRTC
STUN_SERVERS = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
]

# Playback
TICK_INTERVAL = 0.5          # seconds between authoritative ticker checks
TICK_BROADCAST_EVERY = 20    # ticker cycles between position broadcasts (10s)
DRIFT_CORRECTION_AT = 3.0    # client-side seek threshold (seconds)
END_EPSILON = 0.35           # advance this close to the true end
AUTOPLAY_RECENT = 25         # how many recent tracks autoplay avoids repeating
