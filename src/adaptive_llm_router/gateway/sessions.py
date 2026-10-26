"""Bounded in-memory session pinning; stores only model tier, never prompts."""
from __future__ import annotations

import threading
import time


class SessionPins:
    def __init__(self, ttl_seconds: float = 3600, capacity: int = 1024):
        if ttl_seconds <= 0 or capacity < 1:
            raise ValueError("Invalid session cache bounds")
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._pins: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        if not key:
            return None
        now = time.monotonic()
        with self._lock:
            pair = self._pins.get(key)
            if pair is None:
                return None
            if pair[0] <= now:
                del self._pins[key]
                return None
            return dict(pair[1])

    def put(self, key: str, selection: dict) -> None:
        if not key:
            return
        with self._lock:
            now = time.monotonic()
            self._pins = {k: v for k, v in self._pins.items() if v[0] > now}
            if len(self._pins) >= self.capacity and key not in self._pins:
                oldest = min(self._pins, key=lambda k: self._pins[k][0])
                del self._pins[oldest]
            self._pins[key] = (now + self.ttl_seconds, dict(selection))
