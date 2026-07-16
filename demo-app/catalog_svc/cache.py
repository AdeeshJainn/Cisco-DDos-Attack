"""In-process TTL cache for catalog reads.

Two properties matter under load:

- expiry is jittered per key, so a window of popular keys cached at the same
  moment does not expire in the same instant and stampede the database;
- refresh is single-flight: one thread reloads a stale key while the rest
  keep serving the previous value.
"""

import random
import threading
import time
from collections.abc import Callable

TTL_S = 300.0
TTL_JITTER_S = 45.0  # spread of expiry times; keep well under TTL_S


class _Entry:
    __slots__ = ("expires_at", "value")

    def __init__(self, value: dict, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


class TTLCache:
    def __init__(self, ttl_s: float = TTL_S, jitter_s: float = TTL_JITTER_S) -> None:
        self._ttl_s = ttl_s
        self._jitter_s = jitter_s
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._refreshing: set[str] = set()

    def _expiry(self) -> float:
        return time.monotonic() + self._ttl_s + random.uniform(0.0, self._jitter_s)

    def peek(self, key: str) -> dict | None:
        """Return the cached value if present and fresh, else None."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > time.monotonic():
                return entry.value
        return None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._entries[key] = _Entry(value, self._expiry())

    def get(self, key: str, loader: Callable[[], dict]) -> dict:
        """Return the value for key, loading it if stale or missing.

        On a stale hit only one caller pays for the reload; concurrent
        callers are served the previous value until the reload lands.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > time.monotonic():
                return entry.value
            owner = key not in self._refreshing
            if owner:
                self._refreshing.add(key)
        if not owner and entry is not None:
            # Someone else is already reloading: serve stale rather than
            # pile a second load onto the database.
            return entry.value
        # Owner of the refresh, or a cold miss racing the first fill.
        try:
            value = loader()
            self.put(key, value)
            return value
        finally:
            if owner:
                with self._lock:
                    self._refreshing.discard(key)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)
