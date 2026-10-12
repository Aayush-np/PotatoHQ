"""YouTube Music discovery via ytmusicapi.

Strictly metadata: search, artists, albums, playlists, and watch-playlist
related tracks used for autoplay. No audio streaming happens here — playback
is handled by the YouTube embedded player on the client. All calls are sync
(requests under the hood) and are therefore wrapped in asyncio.to_thread by
callers, with a small TTL cache and a concurrency limiter.
"""
import asyncio
import re
import time

from . import models

_client = None
_client_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(4)
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 240
_MAX_CACHED = 300

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class MusicUnavailable(Exception):
    """Raised when YouTube Music can't be reached or returns nothing usable."""


def _client_get():
    global _client
    if _client is None:
        from ytmusicapi import YTMusic

        _client = YTMusic()
    return _client


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(key, value):
    if len(_cache) > _MAX_CACHED:
        for k in list(_cache)[: len(_cache) // 2]:
            _cache.pop(k, None)
    _cache[key] = (time.time() + _CACHE_TTL, value)


async def _call(fn, *args, **kwargs):
    async with _semaphore:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=12)
        except MusicUnavailable:
            raise
        except Exception as e:
            raise MusicUnavailable(str(e)) from e


def _artists_str(item) -> str:
    artists = item.get("artists") or []
    names = [a.get("name") for a in artists if a.get("name")]
    if names:
        return ", ".join(names)
    return item.get("artist") or (item.get("author") or "")


def _artwork(item) -> str | None:
    thumbs = item.get("thumbnails") or item.get("thumbnail") or []
    if isinstance(thumbs, dict):
        thumbs = [thumbs]
    if not thumbs:
        return None
    best = None
    for t in thumbs:
        if not isinstance(t, dict) or not t.get("url"):
            continue
        w = t.get("width") or 60
        if 120 <= w <= 400:
            best = t["url"]
            break
        best = best or t["url"]
    return best


def parse_duration(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    parts = str(s).strip().split(":")
    try:
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def _duration_of(item) -> float | None:
    d = item.get("duration_seconds")
    if d:
        return float(d)
    return parse_duration(item.get("duration") or item.get("length"))


def _song_dict(item) -> dict | None:
    vid = item.get("videoId")
    if not vid or not VIDEO_ID_RE.fullmatch(str(vid)):
        return None
    d = models.track_dict(
        vid, item.get("title"), _artists_str(item), _artwork(item), _duration_of(item)
    )
    # ATV = YouTube Music audio tracks; they reliably allow embedding, while
    # official music videos (OMV) often refuse (YouTube error 101/150).
    d["atv"] = str(item.get("videoType") or "").endswith("ATV")
    return d


def _prefer_atv(songs: list) -> list:
    """Stable sort: audio tracks first, keeping relevance order within groups."""
    return sorted(songs, key=lambda s: 0 if s.get("atv") else 1)


async def search(query: str, filter_name: str = "songs", limit: int = 20) -> dict:
    key = f"search:{filter_name}:{query.lower()}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    async with _client_lock:
        def do():
            return _client_get().search(query, filter=filter_name, limit=limit)

        raw = await _call(do)

    if filter_name == "songs" and not raw:
        # some queries only surface as music videos
        try:
            raw = await _call(lambda: _client_get().search(query, filter="videos", limit=limit))
        except MusicUnavailable:
            raw = []

    if filter_name in ("songs", "videos"):
        out = {"type": "songs", "results": _prefer_atv([s for s in (_song_dict(i) for i in raw) if s])}
    else:
        results = []
        for i in raw:
            rtype = i.get("resultType")
            entry = None
            if filter_name == "artists" and rtype in ("artist",):
                entry = {
                    "kind": "artist", "id": i.get("browseId"),
                    "title": i.get("artist") or i.get("title") or _artists_str(i),
                    "subtitle": _artists_str(i) or "Artist",
                    "artwork": _artwork(i),
                }
            elif filter_name == "albums" and rtype in ("album",):
                entry = {
                    "kind": "album", "id": i.get("browseId"),
                    "title": i.get("title"),
                    "subtitle": _artists_str(i) + (f" · {i['year']}" if i.get("year") else ""),
                    "artwork": _artwork(i),
                }
            elif filter_name == "playlists" and rtype in ("playlist", "community_playlist", "featured_playlist"):
                pid = i.get("browseId") or i.get("playlistId")
                if isinstance(pid, str) and pid.startswith("VL"):
                    pid = pid[2:]
                entry = {
                    "kind": "playlist", "id": pid,
                    "title": i.get("title"),
                    "subtitle": (i.get("author") or "Playlist") + (
                        f" · {i['itemCount']} tracks" if i.get("itemCount") else ""
                    ),
                    "artwork": _artwork(i),
                }
            if entry and entry.get("id"):
                results.append(entry)
        out = {"type": filter_name, "results": results}

    _cache_put(key, out)
    return out


async def related_tracks(video_id: str, limit: int = 20) -> list[dict]:
    """Watch-playlist 'radio' tracks for autoplay."""
    key = f"related:{video_id}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    def do():
        return _client_get().get_watch_playlist(video_id, limit=limit, radio=True)

    data = await _call(do)
    tracks = data.get("tracks") if isinstance(data, dict) else data
    out = _prefer_atv([s for s in (_song_dict(item) for item in tracks or []) if s])
    _cache_put(key, out)
    return out


async def album_tracks(browse_id: str) -> dict:
    key = f"album:{browse_id}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    def do():
        return _client_get().get_album(browse_id)

    data = await _call(do)
    out = {
        "title": data.get("title") or "Album",
        "artist": data.get("artist") or _artists_str(data),
        "artwork": data.get("thumbnails") and _artwork({"thumbnails": data.get("thumbnails")}),
        "tracks": [s for s in (_song_dict(t) for t in data.get("tracks", [])) if s],
    }
    _cache_put(key, out)
    return out


async def playlist_tracks(playlist_id: str) -> dict:
    key = f"playlist:{playlist_id}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    def do():
        return _client_get().get_playlist(playlist_id, limit=100)

    data = await _call(do)
    out = {
        "title": data.get("title") or "Playlist",
        "artwork": _artwork(data),
        "tracks": [s for s in (_song_dict(t) for t in data.get("tracks", [])) if s],
    }
    _cache_put(key, out)
    return out


async def artist_tracks(browse_id: str) -> dict:
    key = f"artist:{browse_id}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    def do():
        return _client_get().get_artist(browse_id)

    data = await _call(do)
    songs = data.get("songs") or {}
    results = songs.get("results") or []
    out = {
        "title": data.get("name") or "Artist",
        "artwork": _artwork(data),
        "tracks": [s for s in (_song_dict(t) for t in results) if s],
    }
    _cache_put(key, out)
    return out
