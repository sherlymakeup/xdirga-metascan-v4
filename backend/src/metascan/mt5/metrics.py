from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading

DEFAULT_SAMPLE_CAPACITY = 256


def _percentile(samples: deque[float] | list[float], p: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    idx = int(round((p / 100.0) * (n - 1)))
    idx = max(0, min(n - 1, idx))
    return ordered[idx]


@dataclass
class GatewayMetrics:
    capacity: int = DEFAULT_SAMPLE_CAPACITY
    poll_cycle_ms: deque[float] = field(init=False)
    call_ms: dict[str, deque[float]] = field(default_factory=dict)
    cycle_overruns: int = 0
    handoff_overruns: int = 0
    handoff_dropped_count: int = 0
    handoff_overrun_active: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.poll_cycle_ms = deque(maxlen=self.capacity)

    def record_cycle_ms(self, ms: float) -> None:
        with self._lock:
            self.poll_cycle_ms.append(ms)

    def record_call_ms(self, name: str, ms: float) -> None:
        with self._lock:
            if name not in self.call_ms:
                self.call_ms[name] = deque(maxlen=self.capacity)
            self.call_ms[name].append(ms)

    def note_handoff_drop(self) -> None:
        with self._lock:
            self.handoff_dropped_count += 1
            self.handoff_overruns += 1
            self.handoff_overrun_active = True

    def clear_handoff_overrun_flag(self) -> None:
        with self._lock:
            self.handoff_overrun_active = False

    def p50(self, samples: deque[float]) -> float | None:
        # copy samples under lock to prevent RuntimeError
        with self._lock:
            copied = list(samples)
        return _percentile(copied, 50)

    def p95(self, samples: deque[float]) -> float | None:
        # copy samples under lock to prevent RuntimeError
        with self._lock:
            copied = list(samples)
        return _percentile(copied, 95)

    def cycle_p50(self) -> float | None:
        with self._lock:
            copied = list(self.poll_cycle_ms)
        return _percentile(copied, 50)

    def cycle_p95(self) -> float | None:
        with self._lock:
            copied = list(self.poll_cycle_ms)
        return _percentile(copied, 95)
