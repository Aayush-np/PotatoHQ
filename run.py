"""PotatoHQ launcher — run `python run.py` and share http://<your-ip>:8420
with your friends. Set POTATO_HOST/POTATO_PORT/POTATO_TURN_* env vars for
internet-facing deployments (see README)."""
import uvicorn

from server.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="info")
