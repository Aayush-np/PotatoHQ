"""Tiny in-memory sliding-window rate limiter."""
import time
from collections import defaultdict, deque

_buckets: dict[str, deque] = defaultdict(deque)


def check(key: str, limit: int, window: float) -> bool:
    """Record an event; return False if over the limit."""
    now = time.time()
    q = _buckets[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
