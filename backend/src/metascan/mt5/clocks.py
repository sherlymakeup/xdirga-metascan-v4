from __future__ import annotations

from typing import Protocol
from datetime import datetime, timezone
import time


class MonotonicClock(Protocol):
    def monotonic(self) -> float: ...


class WallClock(Protocol):
    def now_iso(self) -> str: ...


class SystemMonotonicClock:
    def monotonic(self) -> float:
        return time.monotonic()


class SystemWallClock:
    def now_iso(self) -> str:
        dt = datetime.now(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
