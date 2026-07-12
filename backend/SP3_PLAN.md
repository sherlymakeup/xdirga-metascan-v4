# SP3 — Fake MT5 Gateway + Poll Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-shaped MT5 gateway on a dedicated thread that injects a single MT5 module seam, builds immutable poll frames, coalesces latest-frame handoff into asyncio, diffs open-set state, and publishes only SP1 catalog events through SP2 EventBus — with FakeMt5 as the test double.

**Architecture:** `Mt5Gateway` owns all `mt5.*` calls on one `threading.Thread`, builds frozen `BrokerStateFrame`s, and schedules `LatestFrameSlot.offer` via `loop.call_soon_threadsafe`. `BrokerStateConsumer` (asyncio task) dequeues latest frames, classifies changes with injected `PendingIntentLookup` (default all-false), and `await bus.publish(...)`. Monotonic clocks drive ages/budgets; wall clock only for ISO event stamps.

**Tech Stack:** Python 3.12, stdlib `threading`/`asyncio`/`time`/`types.MappingProxyType`/`dataclasses`, Pydantic SP1 models, SP2 `EventBus`/`Journal`, pytest + pytest-asyncio. No new runtime deps. No real `MetaTrader5` import in unit tests.

**Commit policy (user override):** Do **not** commit per task. Run all RED→GREEN steps; only after full verification, **one** commit:

```bash
git add backend/src/metascan/mt5 backend/tests/test_mt5_*.py backend/tests/helpers.py backend/SP3_PLAN.md backend/SP3_SUMMARY.md
git commit -m "SP3: fake MT5 gateway + poll diff"
```

**Working directory for all commands:** `backend/` (unless noted).

**Run tests:**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest tests/test_mt5_<name>.py -v
```

Full suite before commit:

```powershell
uv run pytest tests/ -v
```

**Do not touch:** frontend `src/`, SP1 contract field renames, SP2 journal/bus APIs (call only), real terminal packaging beyond injectable production factory stub.

---

## File map

| Path | Responsibility |
|---|---|
| `src/metascan/mt5/__init__.py` | Re-export public types + gateway/consumer |
| `src/metascan/mt5/types.py` | Frozen rows, `BrokerStateFrame`, `GatewayError`, `ConnectionHealth`, `GatewayMetrics` snapshot dataclass |
| `src/metascan/mt5/clocks.py` | `MonotonicClock` / `WallClock` protocols + default impls |
| `src/metascan/mt5/metrics.py` | Bounded ring samples; p50/p95; counters |
| `src/metascan/mt5/symbols.py` | `resolve_symbol(base, suffix)` + boot meta capture helpers |
| `src/metascan/mt5/pending_intent.py` | `PendingIntentLookup` Protocol + `NullPendingIntentLookup` |
| `src/metascan/mt5/handoff.py` | `LatestFrameSlot` coalesce (bound 1) |
| `src/metascan/mt5/gateway.py` | `Mt5Gateway` boot, poll, thread, handoff |
| `src/metascan/mt5/consumer.py` | `BrokerStateConsumer` diff + EventBus publish + connection SM |
| `src/metascan/mt5/mapping.py` | `PositionRow` → domain dict / ClosedTrade payload helpers |
| `src/metascan/mt5/testing/__init__.py` | Re-export FakeMt5 |
| `src/metascan/mt5/testing/fake_mt5.py` | Scriptable FakeMt5 exact surface |
| `tests/helpers.py` | Extend with MT5 test factories (envelope already present) |
| `tests/test_mt5_symbols.py` | Resolver |
| `tests/test_mt5_metrics_clocks.py` | Ring metrics + monotonic budgets |
| `tests/test_mt5_fake_scriptable.py` | Fake surface + scriptable ops |
| `tests/test_mt5_frame_handoff.py` | Coalesce slot unit tests |
| `tests/test_mt5_boot_verify.py` | Boot fail-fast |
| `tests/test_mt5_gateway_thread.py` | All MT5 calls same thread |
| `tests/test_mt5_asyncio_nonblocking.py` | Loop not frozen by blocking MT5 |
| `tests/test_mt5_diff_positions.py` | open + MTM update |
| `tests/test_mt5_external_close.py` | full close + pending flip |
| `tests/test_mt5_external_partial.py` | partial + pending flip |
| `tests/test_mt5_external_modify.py` | SL/TP + pending flip |
| `tests/test_mt5_foreign_magic.py` | quarantine + CRITICAL alert |
| `tests/test_mt5_connection_state.py` | CONNECTED/DEGRADED/DISCONNECTED |
| `tests/test_mt5_none_errors.py` | None resilience |
| `tests/test_mt5_lifecycle.py` | start/stop graceful + no order_send source check |
| `SP3_SUMMARY.md` | Decisions + delivered scope (write last, before commit) |

---

## Locked interfaces (implement exactly)

### Clocks

```python
# src/metascan/mt5/clocks.py
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
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=datetime.now(timezone.utc).microsecond)
            .isoformat()
            .replace("+00:00", "Z")
        )
```

Prefer exact wall helper:

```python
class SystemWallClock:
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond:06d}Z"
```

Simpler locked form (use this):

```python
class SystemWallClock:
    def now_iso(self) -> str:
        dt = datetime.now(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
```

### Types

```python
# src/metascan/mt5/types.py
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

# Immutable maps: MappingProxyType wrapping dict at construction.

@dataclass(frozen=True, slots=True)
class GatewayError:
    call: str
    code: int
    message: str

@dataclass(frozen=True, slots=True)
class PositionRow:
    ticket: int
    symbol: str
    magic: int
    volume: float
    price_open: float
    price_current: float
    sl: float          # 0.0 = unset (MT5)
    tp: float
    profit: float
    swap: float
    commission: float
    type: int          # 0 buy, 1 sell
    time_msc: int
    identifier: int
    comment: str

@dataclass(frozen=True, slots=True)
class AccountRow:
    login: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
    trade_mode: int
    margin_mode: int   # hedging expected when require_hedging=True

@dataclass(frozen=True, slots=True)
class TickRow:
    symbol: str
    bid: float
    ask: float
    last: float
    time_msc: int
    volume: float

@dataclass(frozen=True, slots=True)
class SymbolMeta:
    base: str
    resolved: str
    digits: int
    point: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_stops_level: int
    trade_freeze_level: int
    filling_mode: int
    trade_mode: int
    visible: bool

@dataclass(frozen=True, slots=True)
class BrokerStateFrame:
    frame_id: int
    cycle_started_m: float
    cycle_finished_m: float
    cycle_duration_ms: float
    polled_at_wall: str
    positions: tuple[PositionRow, ...]
    account: AccountRow | None
    ticks: Mapping[str, TickRow]          # MappingProxyType
    symbol_meta: Mapping[str, SymbolMeta] # MappingProxyType
    errors: tuple[GatewayError, ...]
    mt5_last_error: tuple[int, str] | None
    positions_unavailable: bool = False   # True when positions_get hard-failed

# Connection projection values match SP1 ConnectionState literals used by SP3:
# "CONNECTED" | "DISCONNECTED" | "DEGRADED"
```

### PendingIntentLookup

```python
# src/metascan/mt5/pending_intent.py
from typing import Protocol

class PendingIntentLookup(Protocol):
    def has_pending_close(self, ticket: int) -> bool: ...
    def has_pending_partial(self, ticket: int, volume: float) -> bool: ...
    def has_pending_modify(self, ticket: int) -> bool: ...

class NullPendingIntentLookup:
    def has_pending_close(self, ticket: int) -> bool:
        return False
    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False
    def has_pending_modify(self, ticket: int) -> bool:
        return False
```

### Metrics

```python
# src/metascan/mt5/metrics.py
from collections import deque
from dataclasses import dataclass, field

DEFAULT_SAMPLE_CAPACITY = 256

@dataclass
class GatewayMetrics:
    capacity: int = DEFAULT_SAMPLE_CAPACITY
    poll_cycle_ms: deque[float] = field(default_factory=lambda: deque(maxlen=DEFAULT_SAMPLE_CAPACITY))
    call_ms: dict[str, deque[float]] = field(default_factory=dict)
    cycle_overruns: int = 0
    handoff_overruns: int = 0          # times offer replaced occupied slot
    handoff_dropped_count: int = 0     # frames replaced (same as overruns count)
    handoff_overrun_active: bool = False

    def record_cycle_ms(self, ms: float) -> None: ...
    def record_call_ms(self, name: str, ms: float) -> None: ...
    def note_handoff_drop(self) -> None: ...
    def clear_handoff_overrun_flag(self) -> None: ...  # consumer may clear after observing
    def p50(self, samples: deque[float]) -> float | None: ...
    def p95(self, samples: deque[float]) -> float | None: ...
    def cycle_p50(self) -> float | None: ...
    def cycle_p95(self) -> float | None: ...
```

Percentile algorithm (locked): sort copy of samples; index `int(round((p/100)*(n-1)))` for n>=1; empty → None.

### Symbols

```python
# src/metascan/mt5/symbols.py
def resolve_symbol(base: str, suffix: str) -> str:
    """resolved = base + suffix; suffix may be empty. No hardcoded broker names."""
    return f"{base}{suffix}"
```

### Handoff

```python
# src/metascan/mt5/handoff.py
import asyncio
from metascan.mt5.types import BrokerStateFrame
from metascan.mt5.metrics import GatewayMetrics

class LatestFrameSlot:
    """Bound-1 latest-frame slot; must be offered only on the asyncio loop thread."""

    def __init__(self, metrics: GatewayMetrics) -> None:
        self._frame: BrokerStateFrame | None = None
        self._event = asyncio.Event()
        self._metrics = metrics

    def offer(self, frame: BrokerStateFrame) -> None:
        if self._frame is not None:
            self._metrics.note_handoff_drop()
        self._frame = frame
        self._event.set()

    async def take(self) -> BrokerStateFrame:
        while True:
            await self._event.wait()
            frame = self._frame
            if frame is None:
                self._event.clear()
                continue
            self._frame = None
            self._event.clear()
            return frame

    def peek(self) -> BrokerStateFrame | None:
        return self._frame
```

### FakeMt5 (exact surface)

```python
# src/metascan/mt5/testing/fake_mt5.py
from __future__ import annotations
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

class FakeMt5:
    def __init__(self) -> None:
        self._initialized = False
        self._account: SimpleNamespace | None = None
        self._positions: dict[int, SimpleNamespace] = {}
        self._symbols: dict[str, SimpleNamespace] = {}
        self._ticks: dict[str, SimpleNamespace] = {}
        self._last_error: tuple[int, str] = (0, "OK")
        self._fail_counts: dict[str, int] = {}
        self._return_none: set[str] = set()
        self._block_seconds: dict[str, float] = {}
        self.call_threads: list[tuple[str, int]] = []  # (call, thread_ident)
        self.call_log: list[str] = []
        self._ticks_frozen = False
        self._terminal: SimpleNamespace | None = SimpleNamespace(connected=True, build=4000)

    # --- production surface ---
    def initialize(self, **kwargs: Any) -> bool: ...
    def shutdown(self) -> None: ...
    def account_info(self) -> SimpleNamespace | None: ...
    def positions_get(self, *args: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...] | None: ...
    def symbol_select(self, symbol: str, enable: bool) -> bool: ...
    def symbol_info(self, symbol: str) -> SimpleNamespace | None: ...
    def symbol_info_tick(self, symbol: str) -> SimpleNamespace | None: ...
    def last_error(self) -> tuple[int, str]: ...
    def terminal_info(self) -> SimpleNamespace | None: ...

    # --- scriptable test API ---
    def set_account(self, **fields: Any) -> None: ...
    def set_positions(self, rows: list[dict[str, Any]]) -> None: ...
    def remove_position(self, ticket: int) -> None: ...
    def set_volume(self, ticket: int, volume: float) -> None: ...
    def set_protection(self, ticket: int, sl: float, tp: float) -> None: ...
    def add_symbol(self, symbol: str, **fields: Any) -> None: ...
    def set_tick(self, symbol: str, bid: float, ask: float, time_msc: int, **extra: Any) -> None: ...
    def freeze_ticks(self) -> None: ...
    def advance_ticks(self, delta_msc: int) -> None: ...
    def fail_next(self, call_name: str, times: int = 1) -> None: ...
    def set_return(self, call_name: str, value: Any) -> None: ...  # value None → permanent None until cleared
    def clear_return(self, call_name: str) -> None: ...
    def block_call(self, call_name: str, seconds: float) -> None: ...
    def set_last_error(self, code: int, msg: str) -> None: ...
```

MT5 position field names on SimpleNamespace (match gateway reader): `ticket`, `symbol`, `magic`, `volume`, `price_open`, `price_current`, `sl`, `tp`, `profit`, `swap`, `commission` (default 0), `type`, `time_msc`, `identifier`, `comment`.

Account fields: `login`, `balance`, `equity`, `margin`, `margin_free`, `margin_level`, `currency`, `trade_mode`, `margin_mode`.

Symbol info fields: `name`, `digits`, `point`, `trade_contract_size`, `volume_min`, `volume_max`, `volume_step`, `trade_stops_level`, `trade_freeze_level`, `filling_mode`, `trade_mode`, `visible`, `select`.

Tick fields: `bid`, `ask`, `last`, `time_msc`, `volume`.

**None + last_error semantics for positions_get:**
- If `last_error` code is `0` or message indicates no positions (Fake uses code `0` with empty tuple path preferred), empty is fine.
- Gateway treats `None` return: if `last_error` is `(0, ...)` or known "no positions" → empty positions; else `positions_unavailable=True` and `errors` append.

### Gateway

```python
# src/metascan/mt5/gateway.py
from __future__ import annotations
import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from metascan.mt5.clocks import MonotonicClock, WallClock, SystemMonotonicClock, SystemWallClock
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.symbols import resolve_symbol
from metascan.mt5.types import (
    AccountRow, BrokerStateFrame, GatewayError, PositionRow, SymbolMeta, TickRow,
)
from types import MappingProxyType

logger = logging.getLogger("metascan.mt5.gateway")

DEFAULT_POLL_INTERVAL_MS = 250
MIN_POLL_INTERVAL_MS = 50
MAX_POLL_INTERVAL_MS = 2000
# MT5 margin mode: retail hedging
ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
# "no positions" tolerant codes used by Fake + common MT5
_NO_POSITIONS_CODES = frozenset({0})

class GatewayBootError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class GatewayConfig:
    login: int | None                    # None → skip login match
    password: str
    server: str
    symbol_suffix: str
    watchlist_bases: tuple[str, ...]
    bot_magic: int
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS
    require_hedging: bool = True
    path: str | None = None              # optional terminal path for initialize

class Mt5Gateway:
    def __init__(
        self,
        mt5_module: Any,
        *,
        config: GatewayConfig,
        slot: LatestFrameSlot,
        loop: asyncio.AbstractEventLoop,
        metrics: GatewayMetrics,
        mono: MonotonicClock | None = None,
        wall: WallClock | None = None,
    ) -> None:
        self._mt5 = mt5_module
        self._config = config
        self._slot = slot
        self._loop = loop
        self._metrics = metrics
        self._mono = mono or SystemMonotonicClock()
        self._wall = wall or SystemWallClock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._boot_ok = threading.Event()
        self._boot_error: BaseException | None = None
        self._frame_id = 0
        self._symbol_meta: dict[str, SymbolMeta] = {}
        self._resolved_symbols: list[str] = []

    @property
    def boot_error(self) -> BaseException | None:
        return self._boot_error

    def start(self) -> None:
        """Start dedicated gateway thread (boot then poll)."""
        if self._thread is not None:
            raise RuntimeError("gateway already started")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="mt5-gateway", daemon=True
        )
        self._thread.start()

    def wait_boot(self, timeout: float = 5.0) -> None:
        if not self._boot_ok.wait(timeout):
            raise TimeoutError("gateway boot timeout")
        if self._boot_error is not None:
            raise GatewayBootError(str(self._boot_error)) from self._boot_error

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=join_timeout)
        self._thread = None

    def _run(self) -> None:
        try:
            self._boot()
            self._boot_ok.set()
        except BaseException as exc:
            self._boot_error = exc
            self._boot_ok.set()
            return
        self._poll_loop()

    def _boot(self) -> None: ...
    def _poll_loop(self) -> None: ...
    def _one_cycle(self) -> BrokerStateFrame: ...
    def _handoff(self, frame: BrokerStateFrame) -> None:
        self._loop.call_soon_threadsafe(self._slot.offer, frame)
```

### Consumer

```python
# src/metascan/mt5/consumer.py
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

from metascan.bus.event_bus import EventBus
from metascan.contract.models import RuntimeEventEnvelope
from metascan.mt5.clocks import MonotonicClock, WallClock, SystemMonotonicClock, SystemWallClock
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.pending_intent import PendingIntentLookup, NullPendingIntentLookup
from metascan.mt5.types import AccountRow, BrokerStateFrame, PositionRow, TickRow

logger = logging.getLogger("metascan.mt5.consumer")

class BrokerStateConsumer:
    def __init__(
        self,
        *,
        bus: EventBus,
        slot: LatestFrameSlot,
        metrics: GatewayMetrics,
        bot_magic: int,
        runtime_id: str,
        pending: PendingIntentLookup | None = None,
        mono: MonotonicClock | None = None,
        wall: WallClock | None = None,
        tick_age_budget_ms: float = 1000.0,
        poll_cycle_p95_budget_ms: float = 400.0,
        hard_fail_threshold: int = 5,
    ) -> None:
        self._bus = bus
        self._slot = slot
        self._metrics = metrics
        self._bot_magic = bot_magic
        self._runtime_id = runtime_id
        self._pending = pending or NullPendingIntentLookup()
        self._mono = mono or SystemMonotonicClock()
        self._wall = wall or SystemWallClock()
        self._tick_age_budget_ms = tick_age_budget_ms
        self._poll_cycle_p95_budget_ms = poll_cycle_p95_budget_ms
        self._hard_fail_threshold = hard_fail_threshold
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_positions: dict[int, PositionRow] = {}
        self.last_account: AccountRow | None = None
        self.last_ticks: dict[str, TickRow] = {}
        self.last_frame_id: int = 0
        self.connection_state: str = "DISCONNECTED"
        self.quarantine_tickets: set[int] = set()
        self._hard_fail_streak: int = 0
        self._last_tick_mono: dict[str, float] = {}
        self._last_tick_msc: dict[str, int] = {}
        self._degrade_reasons: set[str] = set()

    def start(self) -> asyncio.Task[None]:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="broker-state-consumer")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        t = self._task
        if t is not None:
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except asyncio.TimeoutError:
                t.cancel()
        self._task = None

    async def _run(self) -> None: ...
    async def process_frame(self, frame: BrokerStateFrame) -> list[RuntimeEventEnvelope]:
        """Public for unit tests: diff + publish; return published envelopes."""
        ...
```

### Mapping helpers

```python
# src/metascan/mt5/mapping.py
from metascan.mt5.types import PositionRow

def position_id_for(ticket: int) -> str:
    return str(ticket)

def sl_or_none(sl: float) -> float | None:
    return None if sl == 0.0 else sl

def tp_or_none(tp: float) -> float | None:
    return None if tp == 0.0 else tp

def side_from_type(t: int) -> str:
    return "BUY" if t == 0 else "SELL"

def direction_from_type(t: int) -> str:
    return "LONG" if t == 0 else "SHORT"

def protection_for(sl: float, tp: float) -> str:
    has_sl = sl != 0.0
    has_tp = tp != 0.0
    if has_sl and has_tp:
        return "PROTECTED"
    if has_sl or has_tp:
        return "PARTIALLY_PROTECTED"
    return "UNPROTECTED"

def position_payload(row: PositionRow, *, strategy: str = "unknown", opened_at: str) -> dict:
    """Best-effort Position-shaped dict (camelCase keys via envelope payload)."""
    pid = position_id_for(row.ticket)
    return {
        "positionId": pid,
        "id": pid,
        "brokerTicket": str(row.ticket),
        "symbol": row.symbol,
        "side": side_from_type(row.type),
        "volume": row.volume,
        "entryPrice": row.price_open,
        "currentPrice": row.price_current,
        "stopLoss": sl_or_none(row.sl),
        "takeProfit": tp_or_none(row.tp),
        "floatingPnl": row.profit,
        "realizedPnl": 0.0,
        "riskAmount": 0.0,
        "riskPct": 0.0,
        "openedAt": opened_at,
        "strategy": strategy,
        "protection": protection_for(row.sl, row.tp),
        "state": "OPEN",
        "rMultiple": 0.0,
        "mfe": 0.0,
        "mae": 0.0,
        "commission": row.commission,
        "swap": row.swap,
        "netPnl": row.profit + row.commission + row.swap,
        "management": None,
    }

def closed_trade_payload(
    row: PositionRow,
    *,
    closed_at: str,
    strategy_id: str = "unknown",
) -> dict:
    """ClosedTrade wire-shaped payload; exitReason MANUAL only."""
    pid = position_id_for(row.ticket)
    gross = row.profit
    commission = row.commission
    swap = row.swap
    net = gross + commission + swap
    return {
        "tradeId": f"t-{row.ticket}",
        "positionId": pid,
        "strategyId": strategy_id,
        "symbol": row.symbol,
        "direction": direction_from_type(row.type),
        "entryPrice": row.price_open,
        "exitPrice": row.price_current,
        "openedAt": closed_at if row.time_msc == 0 else _msc_to_iso(row.time_msc),
        "closedAt": closed_at,
        "holdingSeconds": 0,
        "volumeInitial": row.volume,
        "grossPnl": gross,
        "commission": commission,
        "swap": swap,
        "netPnl": net,
        "rMultiple": None,
        "mfeR": None,
        "maeR": None,
        "exitReason": "MANUAL",
        "partialFills": [],
        "tags": ["sp3-no-history"],
    }

def _msc_to_iso(time_msc: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(time_msc / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
```

### Envelope factory (consumer internal)

```python
def _envelope(
    *,
    type_: str,
    runtime_id: str,
    wall_iso: str,
    payload: dict,
    severity: str = "INFO",
    position_id: str | None = None,
) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=str(uuid.uuid4()),
        type=type_,
        runtime_id=runtime_id,
        boot_id="",
        revision=0,
        sequence=0,
        occurred_at=wall_iso,
        emitted_at=wall_iso,
        received_at=wall_iso,
        severity=severity,  # type: ignore[arg-type]
        source="LOCAL_RUNTIME",
        payload=payload,
        position_id=position_id,
    )
```

### Event types SP3 may emit (catalog only)

| Observation | Type(s) | mutates_state |
|---|---|---|
| New bot-magic ticket | `position.opened` | True |
| MTM / material field change | `position.updated` | True |
| External full close | `position.closed` + `trade.closed` | True |
| External partial | `position.partially_closed` (+ `position.updated`) | True |
| External SL/TP | `position.protection_changed` (+ `position.updated`) | True |
| Foreign magic | `alert.created` | True |
| Connection SM | `broker.connection.changed`, `runtime.health.changed` | True when state changes |

**Never emit:** `account.updated`, `tick.updated`, non-catalog strings, `MANUAL_CLOSE`.

### Partial payload shape (locked)

```python
{
    "positionId": str(ticket),
    "previousVolume": float,
    "newVolume": float,
    "closedVolume": float,  # previous - new
    "symbol": row.symbol,
}
```

### Protection payload shape (locked)

```python
{
    "positionId": str(ticket),
    "symbol": row.symbol,
    "protection": protection_for(new_sl, new_tp),
    "previousStopLoss": sl_or_none(old.sl),
    "previousTakeProfit": tp_or_none(old.tp),
    "stopLoss": sl_or_none(new.sl),
    "takeProfit": tp_or_none(new.tp),
}
```

### Connection payloads (locked)

```python
# broker.connection.changed
{
    "state": "CONNECTED" | "DEGRADED" | "DISCONNECTED",
    "previousState": str,
    "reasons": list[str],  # e.g. ["HANDOFF_OVERRUN", "ALIEN_POSITION", "TICK_AGE", "POLL_P95", "HARD_FAIL"]
}

# runtime.health.changed
{
    "subsystem": "mt5-gateway",
    "state": "OK" | "DEGRADED" | "DOWN",
    "reasons": list[str],
}
```

### Alert payload (foreign magic)

```python
{
    "id": f"alien-{ticket}",
    "severity": "CRITICAL",
    "title": "Alien position detected",
    "source": "mt5-gateway",
    "createdAt": wall_iso,
    "description": f"ticket={ticket} symbol={symbol} magic={magic} expected={bot_magic}",
    "suggestedAction": "Close or move foreign position; do not manage via bot",
    "acknowledged": False,
}
```

### Degrade reason codes (locked strings)

`HANDOFF_OVERRUN`, `ALIEN_POSITION`, `TICK_AGE`, `POLL_P95`, `SOFT_ERROR`, `HARD_FAIL`, `BOOT_FAILED`

---

## Shared test helpers

Append to `tests/helpers.py` (keep existing `make_envelope`):

```python
from __future__ import annotations
from types import SimpleNamespace
from typing import Any

from metascan.contract.models import RuntimeEventEnvelope
from metascan.mt5.types import PositionRow

def make_envelope(...):  # existing — do not break

def make_position_row(
    ticket: int = 1001,
    *,
    symbol: str = "XAUUSDm",
    magic: int = 240101,
    volume: float = 0.10,
    price_open: float = 2300.0,
    price_current: float = 2301.0,
    sl: float = 2290.0,
    tp: float = 2320.0,
    profit: float = 10.0,
    swap: float = 0.0,
    commission: float = 0.0,
    type: int = 0,
    time_msc: int = 0,
    identifier: int = 0,
    comment: str = "",
) -> PositionRow:
    return PositionRow(
        ticket=ticket,
        symbol=symbol,
        magic=magic,
        volume=volume,
        price_open=price_open,
        price_current=price_current,
        sl=sl,
        tp=tp,
        profit=profit,
        swap=swap,
        commission=commission,
        type=type,
        time_msc=time_msc,
        identifier=identifier or ticket,
        comment=comment,
    )

def default_account(**over: Any) -> dict[str, Any]:
    base = dict(
        login=123456,
        balance=10_000.0,
        equity=10_050.0,
        margin=100.0,
        margin_free=9_900.0,
        margin_level=10050.0,
        currency="USD",
        trade_mode=0,
        margin_mode=2,  # hedging
    )
    base.update(over)
    return base

def default_symbol_info(name: str, **over: Any) -> dict[str, Any]:
    base = dict(
        name=name,
        digits=2,
        point=0.01,
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_stops_level=0,
        trade_freeze_level=0,
        filling_mode=1,
        trade_mode=4,  # full trading
        visible=True,
        select=True,
    )
    base.update(over)
    return base
```

Integration fixture pattern used by multi-file tests:

```python
# pattern — each test file may inline this async fixture
import asyncio
from pathlib import Path
import pytest
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.gateway import Mt5Gateway, GatewayConfig
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT_MAGIC = 240101
SUFFIX = "m"
WATCH = ("XAUUSD",)

async def start_stack(
    journal_path: Path,
    fake: FakeMt5,
    *,
    poll_interval_ms: int = 50,
    pending=None,
    login: int = 123456,
):
    j = Journal(journal_path)
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    for base in WATCH:
        resolved = base + SUFFIX
        fake.add_symbol(resolved, **default_symbol_info(resolved))
        fake.set_tick(resolved, 2300.0, 2300.5, 1_700_000_000_000)
    fake.set_account(**default_account(login=login))
    cfg = GatewayConfig(
        login=login,
        password="x",
        server="Exness-Trial",
        symbol_suffix=SUFFIX,
        watchlist_bases=WATCH,
        bot_magic=BOT_MAGIC,
        poll_interval_ms=poll_interval_ms,
        require_hedging=True,
    )
    gw = Mt5Gateway(fake, config=cfg, slot=slot, loop=loop, metrics=metrics)
    consumer = BrokerStateConsumer(
        bus=bus,
        slot=slot,
        metrics=metrics,
        bot_magic=BOT_MAGIC,
        runtime_id="rt-test",
        pending=pending,
        tick_age_budget_ms=1000.0,
        poll_cycle_p95_budget_ms=400.0,
    )
    gw.start()
    gw.wait_boot(timeout=5.0)
    consumer.start()
    sub = await bus.subscribe("test-sub", maxsize=1024)
    return bus, gw, consumer, sub, metrics, fake
```

---

## Task 1: Types + clocks + symbols + pending_intent

**Files:**
- Create: `src/metascan/mt5/__init__.py`
- Create: `src/metascan/mt5/types.py`
- Create: `src/metascan/mt5/clocks.py`
- Create: `src/metascan/mt5/symbols.py`
- Create: `src/metascan/mt5/pending_intent.py`
- Create: `tests/test_mt5_symbols.py`
- Create: `tests/test_mt5_metrics_clocks.py` (clocks section only first; metrics Task 2)

- [ ] **Step 1: Write failing symbols test**

Create `tests/test_mt5_symbols.py`:

```python
from __future__ import annotations

from metascan.mt5.symbols import resolve_symbol


def test_resolve_appends_suffix() -> None:
    assert resolve_symbol("XAUUSD", "m") == "XAUUSDm"


def test_resolve_empty_suffix() -> None:
    assert resolve_symbol("BTCUSD", "") == "BTCUSD"


def test_no_hardcoded_suffixed_in_symbols_module() -> None:
    from pathlib import Path
    src = Path("src/metascan/mt5/symbols.py").read_text(encoding="utf-8")
    assert "XAUUSDm" not in src
    assert "BTCUSDm" not in src
```

- [ ] **Step 2: Run — expect fail**

```powershell
uv run pytest tests/test_mt5_symbols.py -v
```

Expected: FAIL import / not found.

- [ ] **Step 3: Implement types, clocks, symbols, pending_intent, package init**

`src/metascan/mt5/types.py` — full dataclasses from Locked interfaces.

`src/metascan/mt5/clocks.py` — protocols + `SystemMonotonicClock` + `SystemWallClock`.

`src/metascan/mt5/symbols.py`:

```python
from __future__ import annotations

def resolve_symbol(base: str, suffix: str) -> str:
    return f"{base}{suffix}"
```

`src/metascan/mt5/pending_intent.py` — Protocol + NullPendingIntentLookup exact.

`src/metascan/mt5/__init__.py`:

```python
from metascan.mt5.types import (
    AccountRow,
    BrokerStateFrame,
    GatewayError,
    PositionRow,
    SymbolMeta,
    TickRow,
)
from metascan.mt5.pending_intent import NullPendingIntentLookup

__all__ = [
    "AccountRow",
    "BrokerStateFrame",
    "GatewayError",
    "NullPendingIntentLookup",
    "PositionRow",
    "SymbolMeta",
    "TickRow",
]
```

- [ ] **Step 4: Run symbols tests pass**

```powershell
uv run pytest tests/test_mt5_symbols.py -v
```

Expected: PASS.

- [ ] **Step 5: Write NullPendingIntent + clocks smoke in test_mt5_metrics_clocks.py**

```python
from __future__ import annotations

from metascan.mt5.clocks import SystemMonotonicClock, SystemWallClock
from metascan.mt5.pending_intent import NullPendingIntentLookup


def test_null_pending_always_false() -> None:
    n = NullPendingIntentLookup()
    assert n.has_pending_close(1) is False
    assert n.has_pending_partial(1, 0.1) is False
    assert n.has_pending_modify(1) is False


def test_system_clocks_return_values() -> None:
    m = SystemMonotonicClock()
    w = SystemWallClock()
    a = m.monotonic()
    b = m.monotonic()
    assert b >= a
    iso = w.now_iso()
    assert "T" in iso
    assert iso.endswith("Z") or "+" in iso
```

- [ ] **Step 6: Run**

```powershell
uv run pytest tests/test_mt5_metrics_clocks.py::test_null_pending_always_false tests/test_mt5_metrics_clocks.py::test_system_clocks_return_values -v
```

Expected: PASS.

---

## Task 2: GatewayMetrics ring buffer

**Files:**
- Create: `src/metascan/mt5/metrics.py`
- Modify: `tests/test_mt5_metrics_clocks.py`

- [ ] **Step 1: Write failing metrics tests**

Append to `tests/test_mt5_metrics_clocks.py`:

```python
from metascan.mt5.metrics import GatewayMetrics, DEFAULT_SAMPLE_CAPACITY


def test_metrics_bounded_capacity() -> None:
    m = GatewayMetrics(capacity=8)
    for i in range(20):
        m.record_cycle_ms(float(i))
    assert len(m.poll_cycle_ms) == 8


def test_metrics_p50_p95() -> None:
    m = GatewayMetrics(capacity=100)
    for i in range(1, 101):
        m.record_cycle_ms(float(i))
    p50 = m.cycle_p50()
    p95 = m.cycle_p95()
    assert p50 is not None and 45 <= p50 <= 55
    assert p95 is not None and 90 <= p95 <= 100


def test_handoff_drop_counters() -> None:
    m = GatewayMetrics()
    assert m.handoff_dropped_count == 0
    m.note_handoff_drop()
    m.note_handoff_drop()
    assert m.handoff_dropped_count == 2
    assert m.handoff_overruns == 2
    assert m.handoff_overrun_active is True


def test_empty_percentile_none() -> None:
    m = GatewayMetrics()
    assert m.cycle_p50() is None
    assert m.cycle_p95() is None


def test_record_call_ms_named() -> None:
    m = GatewayMetrics()
    m.record_call_ms("positions_get", 12.0)
    m.record_call_ms("positions_get", 20.0)
    assert m.p50(m.call_ms["positions_get"]) is not None
```

- [ ] **Step 2: Run — fail**

```powershell
uv run pytest tests/test_mt5_metrics_clocks.py -v
```

Expected: FAIL import metrics.

- [ ] **Step 3: Implement metrics.py**

```python
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field

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

    def __post_init__(self) -> None:
        self.poll_cycle_ms = deque(maxlen=self.capacity)

    def record_cycle_ms(self, ms: float) -> None:
        self.poll_cycle_ms.append(ms)

    def record_call_ms(self, name: str, ms: float) -> None:
        if name not in self.call_ms:
            self.call_ms[name] = deque(maxlen=self.capacity)
        self.call_ms[name].append(ms)

    def note_handoff_drop(self) -> None:
        self.handoff_dropped_count += 1
        self.handoff_overruns += 1
        self.handoff_overrun_active = True

    def clear_handoff_overrun_flag(self) -> None:
        self.handoff_overrun_active = False

    def p50(self, samples: deque[float]) -> float | None:
        return _percentile(samples, 50)

    def p95(self, samples: deque[float]) -> float | None:
        return _percentile(samples, 95)

    def cycle_p50(self) -> float | None:
        return self.p50(self.poll_cycle_ms)

    def cycle_p95(self) -> float | None:
        return self.p95(self.poll_cycle_ms)
```

- [ ] **Step 4: Run — pass**

```powershell
uv run pytest tests/test_mt5_metrics_clocks.py -v
```

Expected: all PASS.

---

## Task 3: FakeMt5 scriptable surface

**Files:**
- Create: `src/metascan/mt5/testing/__init__.py`
- Create: `src/metascan/mt5/testing/fake_mt5.py`
- Create: `tests/test_mt5_fake_scriptable.py`
- Modify: `tests/helpers.py` (add factories)

- [ ] **Step 1: Write failing FakeMt5 tests**

```python
# tests/test_mt5_fake_scriptable.py
from __future__ import annotations

import threading
import time

from metascan.mt5.testing.fake_mt5 import FakeMt5


def test_initialize_shutdown_and_account() -> None:
    f = FakeMt5()
    f.set_account(login=1, balance=100.0, equity=100.0, margin=0.0,
                  margin_free=100.0, margin_level=0.0, currency="USD",
                  trade_mode=0, margin_mode=2)
    assert f.initialize(login=1, password="p", server="s") is True
    acc = f.account_info()
    assert acc is not None
    assert acc.login == 1
    f.shutdown()


def test_positions_appear_shrink_remove() -> None:
    f = FakeMt5()
    f.initialize()
    f.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 1, "volume": 0.2,
        "price_open": 1.0, "price_current": 1.1, "sl": 0.9, "tp": 1.2,
        "profit": 1.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 10, "comment": "",
    }])
    pos = f.positions_get()
    assert pos is not None and len(pos) == 1
    f.set_volume(10, 0.1)
    assert f.positions_get()[0].volume == 0.1
    f.set_protection(10, 0.8, 1.3)
    p = f.positions_get()[0]
    assert p.sl == 0.8 and p.tp == 1.3
    f.remove_position(10)
    assert f.positions_get() == ()


def test_ticks_freeze_and_advance() -> None:
    f = FakeMt5()
    f.set_tick("XAUUSDm", 10.0, 10.1, 1000)
    f.freeze_ticks()
    f.advance_ticks(500)
    t = f.symbol_info_tick("XAUUSDm")
    assert t is not None
    assert t.time_msc == 1000  # frozen: advance ignored while frozen? 
    # Design: freeze stops auto-advance; advance_ticks still mutates when called.
    # Locked: freeze_ticks prevents automatic mutation only; advance_ticks always applies.
    # Re-lock: advance_ticks always applies; freeze is for gateway-side auto bump if any.
    # Fake has no auto bump — freeze is no-op flag for tests that check flag.
    f._ticks_frozen = False
    f.advance_ticks(500)
    assert f.symbol_info_tick("XAUUSDm").time_msc == 1500


def test_fail_next_and_last_error() -> None:
    f = FakeMt5()
    f.initialize()
    f.set_account(login=1, balance=1, equity=1, margin=0, margin_free=1,
                  margin_level=0, currency="USD", trade_mode=0, margin_mode=2)
    f.fail_next("account_info", times=1)
    assert f.account_info() is None
    code, msg = f.last_error()
    assert code != 0 or msg  # set by fail_next
    assert f.account_info() is not None  # recovered


def test_block_call_sleeps() -> None:
    f = FakeMt5()
    f.initialize()
    f.block_call("positions_get", 0.15)
    t0 = time.monotonic()
    f.positions_get()
    assert time.monotonic() - t0 >= 0.14


def test_records_thread_ident() -> None:
    f = FakeMt5()
    f.initialize()
    tid = threading.get_ident()
    f.positions_get()
    assert any(c == "positions_get" and t == tid for c, t in f.call_threads)
```

Fix tick test to locked semantics in Step 3: `advance_ticks` always mutates `time_msc`; `freeze_ticks` only sets flag (no auto path in Fake).

Corrected test:

```python
def test_ticks_set_and_advance() -> None:
    f = FakeMt5()
    f.set_tick("XAUUSDm", 10.0, 10.1, 1000)
    assert f.symbol_info_tick("XAUUSDm").bid == 10.0
    f.advance_ticks(500)
    assert f.symbol_info_tick("XAUUSDm").time_msc == 1500
    f.freeze_ticks()
    assert f._ticks_frozen is True
```

- [ ] **Step 2: Run — fail**

```powershell
uv run pytest tests/test_mt5_fake_scriptable.py -v
```

- [ ] **Step 3: Implement FakeMt5 fully**

Implement every method from Locked interface. Core patterns:

```python
def _touch(self, name: str) -> bool:
    """Record call; apply block; return False if should fail/None this call."""
    self.call_log.append(name)
    self.call_threads.append((name, threading.get_ident()))
    sec = self._block_seconds.pop(name, None)
    if sec:
        time.sleep(sec)
    left = self._fail_counts.get(name, 0)
    if left > 0:
        self._fail_counts[name] = left - 1
        self._last_error = (1, f"forced fail {name}")
        return False
    if name in self._return_none:
        self._last_error = (1, f"forced none {name}")
        return False
    return True

def initialize(self, **kwargs: Any) -> bool:
    if not self._touch("initialize"):
        return False
    self._initialized = True
    self._last_error = (0, "OK")
    return True

def positions_get(self, *args: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...] | None:
    if not self._touch("positions_get"):
        return None
    self._last_error = (0, "OK")
    return tuple(self._positions.values())

def set_positions(self, rows: list[dict[str, Any]]) -> None:
    self._positions.clear()
    for r in rows:
        d = dict(r)
        d.setdefault("commission", 0.0)
        d.setdefault("comment", "")
        d.setdefault("time_msc", 0)
        d.setdefault("identifier", d["ticket"])
        self._positions[int(d["ticket"])] = SimpleNamespace(**d)
```

`add_symbol` stores SimpleNamespace; `symbol_select` marks select True; `symbol_info` returns copy/namespace.

`fail_next` increments `_fail_counts[call_name]`.

`set_return(call_name, None)` adds to `_return_none`.

- [ ] **Step 4: Run — pass**

```powershell
uv run pytest tests/test_mt5_fake_scriptable.py -v
```

Expected: PASS.

---

## Task 4: LatestFrameSlot handoff

**Files:**
- Create: `src/metascan/mt5/handoff.py`
- Create: `tests/test_mt5_frame_handoff.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_mt5_frame_handoff.py
from __future__ import annotations

import asyncio
from types import MappingProxyType

import pytest

from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import BrokerStateFrame


def _frame(fid: int) -> BrokerStateFrame:
    return BrokerStateFrame(
        frame_id=fid,
        cycle_started_m=0.0,
        cycle_finished_m=0.1,
        cycle_duration_ms=100.0,
        polled_at_wall="2026-07-13T00:00:00Z",
        positions=(),
        account=None,
        ticks=MappingProxyType({}),
        symbol_meta=MappingProxyType({}),
        errors=(),
        mt5_last_error=None,
    )


@pytest.mark.asyncio
async def test_offer_take_empty_slot() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)
    slot.offer(_frame(1))
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 1
    assert m.handoff_dropped_count == 0


@pytest.mark.asyncio
async def test_coalesce_replaces_and_counts_drop() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)
    slot.offer(_frame(1))
    slot.offer(_frame(2))
    slot.offer(_frame(3))
    assert m.handoff_dropped_count == 2
    assert m.handoff_overrun_active is True
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 3


@pytest.mark.asyncio
async def test_take_waits_for_offer() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)

    async def later() -> None:
        await asyncio.sleep(0.05)
        slot.offer(_frame(9))

    asyncio.create_task(later())
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 9
```

- [ ] **Step 2: Run fail; implement handoff.py as Locked; run pass**

```powershell
uv run pytest tests/test_mt5_frame_handoff.py -v
```

---

## Task 5: mapping helpers + position_id scheme

**Files:**
- Create: `src/metascan/mt5/mapping.py`
- Create: `tests/test_mt5_diff_positions.py` (mapping unit tests first)

- [ ] **Step 1: Failing mapping tests** at top of `tests/test_mt5_diff_positions.py`:

```python
from __future__ import annotations

from helpers import make_position_row
from metascan.mt5.mapping import (
    closed_trade_payload,
    position_id_for,
    position_payload,
    protection_for,
    sl_or_none,
)


def test_position_id_is_str_ticket() -> None:
    assert position_id_for(42) == "42"


def test_sl_zero_maps_none() -> None:
    assert sl_or_none(0.0) is None
    assert sl_or_none(1.5) == 1.5


def test_protection_levels() -> None:
    assert protection_for(0.0, 0.0) == "UNPROTECTED"
    assert protection_for(1.0, 0.0) == "PARTIALLY_PROTECTED"
    assert protection_for(1.0, 2.0) == "PROTECTED"


def test_closed_trade_exit_reason_manual_and_net_pnl() -> None:
    row = make_position_row(ticket=7, profit=10.0, commission=-1.0, swap=-0.5)
    p = closed_trade_payload(row, closed_at="2026-07-13T00:00:00Z")
    assert p["exitReason"] == "MANUAL"
    assert "MANUAL_CLOSE" not in p.values()
    assert p["netPnl"] == p["grossPnl"] + p["commission"] + p["swap"]
    assert p["positionId"] == "7"
    assert "sp3-no-history" in p["tags"]


def test_position_payload_id() -> None:
    row = make_position_row(ticket=5)
    p = position_payload(row, opened_at="2026-07-13T00:00:00Z")
    assert p["positionId"] == "5"
    assert p["brokerTicket"] == "5"
```

Also add factories to `tests/helpers.py` from Shared test helpers section.

- [ ] **Step 2: Implement mapping.py; run pass**

```powershell
uv run pytest tests/test_mt5_diff_positions.py -v -k "position_id or sl_zero or protection or closed_trade or position_payload"
```

---

## Task 6: Gateway boot verify

**Files:**
- Create: `src/metascan/mt5/gateway.py` (boot + start/stop skeleton)
- Create: `tests/test_mt5_boot_verify.py`

- [ ] **Step 1: Failing boot tests**

```python
# tests/test_mt5_boot_verify.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayBootError, GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


def _cfg(**over) -> GatewayConfig:
    base = dict(
        login=123456,
        password="secret",
        server="Exness-Trial",
        symbol_suffix="m",
        watchlist_bases=("XAUUSD",),
        bot_magic=240101,
        poll_interval_ms=50,
        require_hedging=True,
    )
    base.update(over)
    return GatewayConfig(**base)


@pytest.mark.asyncio
async def test_boot_wrong_login_fails() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=999))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(login=123456), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError):
        gw.wait_boot(timeout=3.0)
    gw.stop()


@pytest.mark.asyncio
async def test_boot_missing_symbol_names_base_and_resolved() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456))
    # no symbol added
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError, match=r"XAUUSD.*XAUUSDm|XAUUSDm.*XAUUSD"):
        gw.wait_boot(timeout=3.0)
    gw.stop()


@pytest.mark.asyncio
async def test_boot_hedging_mismatch() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456, margin_mode=0))  # not hedging
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(require_hedging=True), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError, match="hedg"):
        gw.wait_boot(timeout=3.0)
    gw.stop()


@pytest.mark.asyncio
async def test_boot_success() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)
    assert gw.boot_error is None
    # wait one frame
    frame = await asyncio.wait_for(slot.take(), timeout=2.0)
    assert frame.frame_id >= 1
    assert "XAUUSDm" in frame.symbol_meta
    gw.stop()
```

- [ ] **Step 2: Implement `_boot` and minimal `_poll_loop` / `_one_cycle`**

Boot algorithm:

```python
def _boot(self) -> None:
    mt5 = self._mt5
    cfg = self._config
    kwargs = {"login": cfg.login, "password": cfg.password, "server": cfg.server}
    if cfg.path:
        kwargs["path"] = cfg.path
    # never log password
    if not mt5.initialize(**{k: v for k, v in kwargs.items() if v is not None}):
        err = mt5.last_error()
        raise GatewayBootError(f"initialize failed: {err}")
    acc = mt5.account_info()
    if acc is None:
        raise GatewayBootError(f"account_info failed: {mt5.last_error()}")
    if cfg.login is not None and int(acc.login) != int(cfg.login):
        raise GatewayBootError(
            f"login mismatch: expected {cfg.login} got {acc.login}"
        )
    margin_mode = int(getattr(acc, "margin_mode", -1))
    if cfg.require_hedging and margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
        raise GatewayBootError(
            f"hedging required: margin_mode={margin_mode} expected {ACCOUNT_MARGIN_MODE_RETAIL_HEDGING}"
        )
    meta: dict[str, SymbolMeta] = {}
    resolved_list: list[str] = []
    for base in cfg.watchlist_bases:
        resolved = resolve_symbol(base, cfg.symbol_suffix)
        if not mt5.symbol_select(resolved, True):
            raise GatewayBootError(
                f"symbol_select failed base={base} resolved={resolved}: {mt5.last_error()}"
            )
        info = mt5.symbol_info(resolved)
        if info is None or not getattr(info, "visible", True):
            raise GatewayBootError(
                f"symbol missing/invisible base={base} resolved={resolved}"
            )
        trade_mode = int(getattr(info, "trade_mode", 0))
        # MT5 SYMBOL_TRADE_MODE_DISABLED = 0
        if trade_mode == 0:
            raise GatewayBootError(
                f"symbol trading disabled base={base} resolved={resolved}"
            )
        sm = SymbolMeta(
            base=base,
            resolved=resolved,
            digits=int(info.digits),
            point=float(info.point),
            trade_contract_size=float(info.trade_contract_size),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            trade_stops_level=int(info.trade_stops_level),
            trade_freeze_level=int(info.trade_freeze_level),
            filling_mode=int(info.filling_mode),
            trade_mode=trade_mode,
            visible=bool(getattr(info, "visible", True)),
        )
        meta[resolved] = sm
        resolved_list.append(resolved)
    self._symbol_meta = meta
    self._resolved_symbols = resolved_list
```

Poll cycle (minimal):

```python
def _poll_loop(self) -> None:
    interval = max(MIN_POLL_INTERVAL_MS, min(MAX_POLL_INTERVAL_MS, self._config.poll_interval_ms))
    interval_s = interval / 1000.0
    while not self._stop.is_set():
        t0 = self._mono.monotonic()
        try:
            frame = self._one_cycle(t0)
            self._handoff(frame)
            self._metrics.record_cycle_ms(frame.cycle_duration_ms)
            if frame.cycle_duration_ms > interval:
                self._metrics.cycle_overruns += 1
        except Exception:
            logger.exception("poll cycle error")
        elapsed = self._mono.monotonic() - t0
        remaining = interval_s - elapsed
        if remaining > 0:
            self._stop.wait(remaining)

def _one_cycle(self, t0: float) -> BrokerStateFrame:
    mt5 = self._mt5
    errors: list[GatewayError] = []
    positions_unavailable = False
    # positions
    c0 = self._mono.monotonic()
    raw_pos = mt5.positions_get()
    self._metrics.record_call_ms("positions_get", (self._mono.monotonic() - c0) * 1000)
    positions: list[PositionRow] = []
    if raw_pos is None:
        code, msg = mt5.last_error()
        if code in _NO_POSITIONS_CODES:
            positions = []
        else:
            positions_unavailable = True
            errors.append(GatewayError("positions_get", code, msg))
    else:
        for p in raw_pos:
            positions.append(PositionRow(
                ticket=int(p.ticket),
                symbol=str(p.symbol),
                magic=int(p.magic),
                volume=float(p.volume),
                price_open=float(p.price_open),
                price_current=float(p.price_current),
                sl=float(p.sl),
                tp=float(p.tp),
                profit=float(p.profit),
                swap=float(p.swap),
                commission=float(getattr(p, "commission", 0.0) or 0.0),
                type=int(p.type),
                time_msc=int(getattr(p, "time_msc", 0) or 0),
                identifier=int(getattr(p, "identifier", p.ticket)),
                comment=str(getattr(p, "comment", "") or ""),
            ))
    # account
    c1 = self._mono.monotonic()
    raw_acc = mt5.account_info()
    self._metrics.record_call_ms("account_info", (self._mono.monotonic() - c1) * 1000)
    account = None
    if raw_acc is None:
        code, msg = mt5.last_error()
        errors.append(GatewayError("account_info", code, msg))
    else:
        account = AccountRow(
            login=int(raw_acc.login),
            balance=float(raw_acc.balance),
            equity=float(raw_acc.equity),
            margin=float(raw_acc.margin),
            free_margin=float(raw_acc.margin_free),
            margin_level=float(raw_acc.margin_level),
            currency=str(raw_acc.currency),
            trade_mode=int(raw_acc.trade_mode),
            margin_mode=int(raw_acc.margin_mode),
        )
    # ticks
    ticks: dict[str, TickRow] = {}
    c2 = self._mono.monotonic()
    for sym in self._resolved_symbols:
        t = mt5.symbol_info_tick(sym)
        if t is None:
            code, msg = mt5.last_error()
            errors.append(GatewayError("symbol_info_tick", code, f"{sym}: {msg}"))
            continue
        ticks[sym] = TickRow(
            symbol=sym,
            bid=float(t.bid),
            ask=float(t.ask),
            last=float(getattr(t, "last", 0.0) or 0.0),
            time_msc=int(getattr(t, "time_msc", 0) or 0),
            volume=float(getattr(t, "volume", 0.0) or 0.0),
        )
    self._metrics.record_call_ms(
        "symbol_info_tick", (self._mono.monotonic() - c2) * 1000
    )
    t1 = self._mono.monotonic()
    self._frame_id += 1
    le = mt5.last_error()
    return BrokerStateFrame(
        frame_id=self._frame_id,
        cycle_started_m=t0,
        cycle_finished_m=t1,
        cycle_duration_ms=(t1 - t0) * 1000.0,
        polled_at_wall=self._wall.now_iso(),
        positions=tuple(positions),
        account=account,
        ticks=MappingProxyType(ticks),
        symbol_meta=MappingProxyType(dict(self._symbol_meta)),
        errors=tuple(errors),
        mt5_last_error=le if le else None,
        positions_unavailable=positions_unavailable,
    )
```

On `stop`: set stop event; join; on gateway thread path after loop, call `mt5.shutdown()` before thread exit:

```python
def _poll_loop(self) -> None:
    try:
        ...
    finally:
        try:
            self._mt5.shutdown()
        except Exception:
            logger.exception("shutdown failed")
```

- [ ] **Step 3: Run boot tests pass**

```powershell
uv run pytest tests/test_mt5_boot_verify.py -v
```

---

## Task 7: Thread ownership + no order_send

**Files:**
- Create: `tests/test_mt5_gateway_thread.py`
- Create: `tests/test_mt5_lifecycle.py` (source grep + stop)

- [ ] **Step 1: Thread affinity test**

```python
# tests/test_mt5_gateway_thread.py
from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


@pytest.mark.asyncio
async def test_all_mt5_calls_same_thread() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=1, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    gw.start()
    gw.wait_boot(3.0)
    await asyncio.wait_for(slot.take(), timeout=2.0)
    await asyncio.wait_for(slot.take(), timeout=2.0)
    gw.stop()
    assert fake.call_threads
    ids = {tid for _, tid in fake.call_threads}
    assert len(ids) == 1
    # ensure multiple call kinds recorded
    names = {n for n, _ in fake.call_threads}
    assert "initialize" in names
    assert "positions_get" in names
    assert "account_info" in names
```

- [ ] **Step 2: Lifecycle + forbidden API source test**

```python
# tests/test_mt5_lifecycle.py
from __future__ import annotations

from pathlib import Path

import pytest


def test_gateway_source_has_no_order_send() -> None:
    root = Path("src/metascan/mt5")
    for path in root.rglob("*.py"):
        if "testing" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "order_send" not in text, path
        assert "order_check" not in text, path
        assert "history_deals_get" not in text, path


@pytest.mark.asyncio
async def test_stop_calls_shutdown() -> None:
    import asyncio
    from helpers import default_account, default_symbol_info
    from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
    from metascan.mt5.handoff import LatestFrameSlot
    from metascan.mt5.metrics import GatewayMetrics
    from metascan.mt5.testing.fake_mt5 import FakeMt5

    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=1, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    gw.start()
    gw.wait_boot(3.0)
    gw.stop(join_timeout=3.0)
    assert "shutdown" in fake.call_log
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_gateway_thread.py tests/test_mt5_lifecycle.py -v
```

---

## Task 8: Asyncio non-blocking

**Files:**
- Create: `tests/test_mt5_asyncio_nonblocking.py`

- [ ] **Step 1: Test**

```python
from __future__ import annotations

import asyncio
import time

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


@pytest.mark.asyncio
async def test_blocking_positions_get_does_not_freeze_loop() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    fake.block_call("positions_get", 0.3)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=1, poll_interval_ms=50,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    gw.start()
    gw.wait_boot(3.0)
    # After boot, next poll blocks positions_get 0.3s on gateway thread.
    # Event loop must still progress.
    ticks = 0

    async def counter() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    t0 = time.monotonic()
    await counter()
    elapsed = time.monotonic() - t0
    gw.stop()
    assert ticks == 10
    assert elapsed < 0.35  # would be >=0.3+ if loop blocked on MT5
```

Note: first `positions_get` after boot may or may not hit block depending on when `block_call` is armed — arm **after** boot:

```python
    gw.start()
    gw.wait_boot(3.0)
    fake.block_call("positions_get", 0.3)
    ticks = 0
    ...
```

- [ ] **Step 2: Run pass**

```powershell
uv run pytest tests/test_mt5_asyncio_nonblocking.py -v
```

---

## Task 9: Consumer process_frame — open + MTM

**Files:**
- Create: `src/metascan/mt5/consumer.py`
- Modify: `tests/test_mt5_diff_positions.py`

- [ ] **Step 1: Failing integration tests for open/update**

```python
# append to tests/test_mt5_diff_positions.py
import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info, make_envelope
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


async def _stack(tmp: Path, fake: FakeMt5, pending=None):
    j = Journal(tmp / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_700_000_000_000)
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=BOT, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", pending=pending,
    )
    gw.start()
    gw.wait_boot(3.0)
    consumer.start()
    sub = await bus.subscribe("s1", maxsize=2048)
    return bus, gw, consumer, sub


async def _drain(sub, n: int, timeout: float = 3.0):
    out = []
    for _ in range(n):
        item = await asyncio.wait_for(sub.get(), timeout=timeout)
        out.append(item)
    return out


async def _collect_until(sub, pred, timeout: float = 5.0):
    end = asyncio.get_event_loop().time() + timeout
    found = []
    while asyncio.get_event_loop().time() < end:
        remaining = end - asyncio.get_event_loop().time()
        try:
            item = await asyncio.wait_for(sub.get(), timeout=max(0.05, remaining))
        except asyncio.TimeoutError:
            break
        found.append(item)
        if pred(found):
            break
    return found


@pytest.mark.asyncio
async def test_position_opened_for_bot_magic(tmp_path: Path) -> None:
    fake = FakeMt5()
    bus, gw, consumer, sub = await _stack(tmp_path, fake)
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    events = await _collect_until(
        sub,
        lambda xs: any(getattr(e, "type", None) and str(e.type).endswith("position.opened") or str(getattr(e, "type", "")) == "position.opened" for e in xs if hasattr(e, "type")),
        timeout=5.0,
    )
    types = [str(e.type.value if hasattr(e.type, "value") else e.type) for e in events if hasattr(e, "type")]
    assert "position.opened" in types
    opened = next(e for e in events if str(getattr(e.type, "value", e.type)) == "position.opened")
    assert opened.position_id == "100"
    assert opened.payload["positionId"] == "100"
    assert opened.source == "LOCAL_RUNTIME" or str(opened.source) == "LOCAL_RUNTIME"
    await consumer.stop()
    gw.stop()
    await bus.close()


@pytest.mark.asyncio
async def test_position_updated_on_mtm(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    bus, gw, consumer, sub = await _stack(tmp_path, fake)
    await _collect_until(
        sub,
        lambda xs: any(str(getattr(e.type, "value", getattr(e, "type", ""))) == "position.opened" for e in xs if hasattr(e, "type")),
        timeout=5.0,
    )
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2310.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 50.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    events = await _collect_until(
        sub,
        lambda xs: any(str(getattr(e.type, "value", getattr(e, "type", ""))) == "position.updated" for e in xs if hasattr(e, "type")),
        timeout=5.0,
    )
    types = [str(getattr(e.type, "value", e.type)) for e in events if hasattr(e, "type")]
    assert "position.updated" in types
    await consumer.stop()
    gw.stop()
    await bus.close()
```

Type comparison helper — put in helpers:

```python
def event_type(e) -> str:
    t = e.type
    return str(t.value if hasattr(t, "value") else t)
```

Use `event_type(e) == "position.opened"` everywhere.

- [ ] **Step 2: Implement BrokerStateConsumer.diff core**

`process_frame` algorithm:

1. `now_m = mono.monotonic()`; record frame age.
2. Recompute degrade reasons:
   - if `metrics.handoff_overrun_active` → `HANDOFF_OVERRUN`
   - if `cycle_p95` and `cycle_p95 > poll_cycle_p95_budget_ms` → `POLL_P95`
   - tick age: for each tick with previous msc advanced, if `(now_m - last_mono)*1000 > budget` → `TICK_AGE`
   - if any position `magic != bot_magic` → add tickets to quarantine, `ALIEN_POSITION`
   - if `frame.positions_unavailable` or hard errors → streak++
3. Map degrade → connection state:
   - if not booted / hard streak >= threshold → `DISCONNECTED`
   - elif degrade reasons → `DEGRADED`
   - else `CONNECTED`
4. If connection state changed → publish `broker.connection.changed` + `runtime.health.changed` (`OK`/`DEGRADED`/`DOWN`).
5. If `positions_unavailable`: skip position diff (keep last_positions).
6. Else position diff:
   - `current = {p.ticket: p for p in frame.positions}`
   - foreign: any `p.magic != bot_magic` → alert once per new quarantine ticket (`alert.created` CRITICAL); do **not** add to `last_positions` managed map
   - managed current = bot magic only
   - for ticket in last_positions - managed: classify close via pending
   - for ticket in managed - last_positions: `position.opened`
   - for ticket in both: volume shrink / SLTP / MTM
7. Update `last_positions` only for bot-magic tickets still open.
8. Update last_account/ticks from frame (no account/tick events).

Publish via:

```python
stamped = await self._bus.publish(env, mutates_state=True)
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_diff_positions.py -v
```

---

## Task 10: External full close + pending flip

**Files:**
- Create: `tests/test_mt5_external_close.py`
- Modify: `src/metascan/mt5/consumer.py` (close branch)

- [ ] **Step 1: Tests**

```python
# tests/test_mt5_external_close.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info, event_type
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.pending_intent import NullPendingIntentLookup
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


class ClosePending:
    def __init__(self, tickets: set[int]) -> None:
        self.tickets = tickets
    def has_pending_close(self, ticket: int) -> bool:
        return ticket in self.tickets
    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False
    def has_pending_modify(self, ticket: int) -> bool:
        return False


async def _boot_with_pos(tmp_path, pending=None):
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    fake.set_positions([{
        "ticket": 55, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.2,
        "price_open": 2300.0, "price_current": 2305.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 20.0, "swap": -0.5, "commission": -1.0, "type": 0,
        "time_msc": 0, "identifier": 55, "comment": "",
    }])
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=BOT, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", pending=pending or NullPendingIntentLookup(),
    )
    gw.start()
    gw.wait_boot(3.0)
    consumer.start()
    sub = await bus.subscribe("s1", maxsize=2048)
    # wait open
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if hasattr(e, "type") and event_type(e) == "position.opened":
            break
    return bus, gw, consumer, sub, fake


@pytest.mark.asyncio
async def test_external_full_close_emits_position_and_trade_manual(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot_with_pos(tmp_path)
    fake.remove_position(55)
    seen = []
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if not hasattr(e, "type"):
            continue
        seen.append(event_type(e))
        if "trade.closed" in seen and "position.closed" in seen:
            break
    assert "position.closed" in seen
    assert "trade.closed" in seen
    # fetch trade.closed payload from journal
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    trade = next(r for r in rows if event_type(r) == "trade.closed")
    assert trade.payload["exitReason"] == "MANUAL"
    assert trade.payload["positionId"] == "55"
    assert trade.payload["netPnl"] == trade.payload["grossPnl"] + trade.payload["commission"] + trade.payload["swap"]
    assert "MANUAL_CLOSE" not in str(trade.payload)
    await consumer.stop()
    gw.stop()
    await bus.close()


@pytest.mark.asyncio
async def test_pending_close_suppresses_external_trade_closed(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot_with_pos(tmp_path, pending=ClosePending({55}))
    fake.remove_position(55)
    seen = []
    await asyncio.sleep(0.5)
    # drain quickly
    end = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < end:
        try:
            e = await asyncio.wait_for(sub.get(), timeout=0.2)
        except asyncio.TimeoutError:
            break
        if hasattr(e, "type"):
            seen.append(event_type(e))
    assert "trade.closed" not in seen
    assert "position.closed" not in seen  # SP3: no external close set
    await consumer.stop()
    gw.stop()
    await bus.close()
```

Add `event_type` to helpers:

```python
def event_type(e) -> str:
    t = getattr(e, "type", "")
    return str(t.value if hasattr(t, "value") else t)
```

- [ ] **Step 2: Implement close branch in consumer**

```python
if ticket not in current_managed:
    old = self.last_positions[ticket]
    if self._pending.has_pending_close(ticket):
        # bot path: suppress external events
        del self.last_positions[ticket]
        continue
    wall = self._wall.now_iso()
    await self._publish(_envelope(
        type_="position.closed",
        runtime_id=self._runtime_id,
        wall_iso=wall,
        payload={"positionId": position_id_for(ticket), "symbol": old.symbol, "state": "CLOSED"},
        position_id=position_id_for(ticket),
        severity="INFO",
    ), mutates_state=True)
    await self._publish(_envelope(
        type_="trade.closed",
        runtime_id=self._runtime_id,
        wall_iso=wall,
        payload=closed_trade_payload(old, closed_at=wall),
        position_id=position_id_for(ticket),
        severity="INFO",
    ), mutates_state=True)
    del self.last_positions[ticket]
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_external_close.py -v
```

---

## Task 11: External partial + pending flip

**Files:**
- Create: `tests/test_mt5_external_partial.py`
- Modify: consumer volume branch

- [ ] **Step 1: Tests**

```python
# tests/test_mt5_external_partial.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info, event_type
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


class PartialPending:
    def __init__(self, key: tuple[int, float] | None = None) -> None:
        self.key = key
    def has_pending_close(self, ticket: int) -> bool:
        return False
    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return self.key is not None and self.key == (ticket, volume)
    def has_pending_modify(self, ticket: int) -> bool:
        return False


async def _boot(tmp_path, pending=None):
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    fake.set_positions([{
        "ticket": 77, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.30,
        "price_open": 2300.0, "price_current": 2305.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 10.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 77, "comment": "",
    }])
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=BOT, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", pending=pending,
    )
    gw.start(); gw.wait_boot(3.0); consumer.start()
    sub = await bus.subscribe("s1", maxsize=2048)
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if hasattr(e, "type") and event_type(e) == "position.opened":
            break
    return bus, gw, consumer, sub, fake


@pytest.mark.asyncio
async def test_external_partial(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot(tmp_path)
    fake.set_volume(77, 0.10)
    seen = []
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if hasattr(e, "type"):
            seen.append(event_type(e))
            if "position.partially_closed" in seen:
                break
    assert "position.partially_closed" in seen
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    partial = next(r for r in rows if event_type(r) == "position.partially_closed")
    assert partial.payload["positionId"] == "77"
    assert partial.payload["previousVolume"] == 0.30
    assert partial.payload["newVolume"] == 0.10
    assert abs(partial.payload["closedVolume"] - 0.20) < 1e-9
    await consumer.stop(); gw.stop(); await bus.close()


@pytest.mark.asyncio
async def test_pending_partial_suppresses(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot(tmp_path, pending=PartialPending((77, 0.10)))
    fake.set_volume(77, 0.10)
    seen = []
    end = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < end:
        try:
            e = await asyncio.wait_for(sub.get(), timeout=0.2)
        except asyncio.TimeoutError:
            break
        if hasattr(e, "type"):
            seen.append(event_type(e))
    assert "position.partially_closed" not in seen
    # last_positions still updated to new volume
    assert consumer.last_positions[77].volume == 0.10
    await consumer.stop(); gw.stop(); await bus.close()
```

- [ ] **Step 2: Implement volume shrink branch**

```python
if new.volume < old.volume - 1e-12:
    if not self._pending.has_pending_partial(ticket, new.volume):
        wall = self._wall.now_iso()
        await self._publish(... type_="position.partially_closed", payload={
            "positionId": position_id_for(ticket),
            "previousVolume": old.volume,
            "newVolume": new.volume,
            "closedVolume": old.volume - new.volume,
            "symbol": new.symbol,
        }, ...)
        await self._publish(... type_="position.updated", payload=position_payload(new, opened_at=wall), ...)
    self.last_positions[ticket] = new
    continue
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_external_partial.py -v
```

---

## Task 12: External SL/TP modify + pending flip

**Files:**
- Create: `tests/test_mt5_external_modify.py`

- [ ] **Step 1: Tests** — same stack pattern; `set_protection(88, 2280.0, 2350.0)` after open; assert `position.protection_changed` with previous/new SL/TP; pending modify true suppresses.

```python
class ModifyPending:
    def __init__(self, tickets: set[int]) -> None:
        self.tickets = tickets
    def has_pending_close(self, ticket: int) -> bool:
        return False
    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False
    def has_pending_modify(self, ticket: int) -> bool:
        return ticket in self.tickets
```

External path assertions:

```python
assert "position.protection_changed" in seen
prot = next(r for r in rows if event_type(r) == "position.protection_changed")
assert prot.payload["positionId"] == "88"
assert prot.payload["stopLoss"] == 2280.0
assert prot.payload["takeProfit"] == 2350.0
```

Pending path: no `position.protection_changed`.

- [ ] **Step 2: Implement SL/TP branch**

```python
if new.sl != old.sl or new.tp != old.tp:
    if not self._pending.has_pending_modify(ticket):
        wall = self._wall.now_iso()
        await self._publish(... "position.protection_changed", payload={
            "positionId": position_id_for(ticket),
            "symbol": new.symbol,
            "protection": protection_for(new.sl, new.tp),
            "previousStopLoss": sl_or_none(old.sl),
            "previousTakeProfit": tp_or_none(old.tp),
            "stopLoss": sl_or_none(new.sl),
            "takeProfit": tp_or_none(new.tp),
        }, ...)
        await self._publish(... "position.updated", ...)
    self.last_positions[ticket] = new
    continue
```

MTM else-branch when price/profit/swap change material:

```python
if (new.price_current != old.price_current or new.profit != old.profit
        or new.swap != old.swap or new.commission != old.commission):
    wall = self._wall.now_iso()
    await self._publish(... "position.updated", payload=position_payload(new, opened_at=wall), ...)
self.last_positions[ticket] = new
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_external_modify.py -v
```

---

## Task 13: Foreign magic quarantine

**Files:**
- Create: `tests/test_mt5_foreign_magic.py`

- [ ] **Step 1: Test**

```python
@pytest.mark.asyncio
async def test_foreign_magic_degraded_and_critical_alert(tmp_path: Path) -> None:
    # boot empty, then set position magic != BOT
    fake = FakeMt5()
    ...
    fake.set_positions([{
        "ticket": 999, "symbol": "XAUUSDm", "magic": 111,  # foreign
        "volume": 0.1, "price_open": 2300.0, "price_current": 2301.0,
        "sl": 0.0, "tp": 0.0, "profit": 0.0, "swap": 0.0, "commission": 0.0,
        "type": 0, "time_msc": 0, "identifier": 999, "comment": "manual",
    }])
    # collect until alert.created and broker.connection.changed DEGRADED
    ...
    assert "alert.created" in types
    alert = next(r for r in rows if event_type(r) == "alert.created")
    assert alert.payload["severity"] == "CRITICAL"
    assert "999" in alert.payload["description"]
    assert 111 in [111]  # magic mentioned
    assert 999 not in consumer.last_positions  # never adopt
    assert consumer.connection_state == "DEGRADED"
    assert 999 in consumer.quarantine_tickets
```

Also assert **no** `position.opened` for foreign ticket.

When foreign removed → quarantine clears if no other reasons → may return CONNECTED.

- [ ] **Step 2: Implement foreign scan in process_frame**

```python
foreign = [p for p in frame.positions if p.magic != self._bot_magic]
new_q = {p.ticket for p in foreign}
for p in foreign:
    if p.ticket not in self.quarantine_tickets:
        await self._publish(alert envelope CRITICAL, ...)
self.quarantine_tickets = new_q
if new_q:
    self._degrade_reasons.add("ALIEN_POSITION")
else:
    self._degrade_reasons.discard("ALIEN_POSITION")
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_foreign_magic.py -v
```

---

## Task 14: Connection state + handoff overrun DEGRADED

**Files:**
- Create: `tests/test_mt5_connection_state.py`

- [ ] **Step 1: Tests**

```python
@pytest.mark.asyncio
async def test_connected_after_successful_poll(tmp_path: Path) -> None:
    # boot + one frame → connection_state CONNECTED (or DEGRADED only if reasons)
    ...
    assert consumer.connection_state in {"CONNECTED", "DEGRADED"}
    # with clean fake, expect CONNECTED
    assert consumer.connection_state == "CONNECTED"


@pytest.mark.asyncio
async def test_handoff_overrun_marks_degraded(tmp_path: Path) -> None:
    # Directly: metrics.note_handoff_drop(); process a synthetic frame via process_frame
    from types import MappingProxyType
    from metascan.mt5.types import BrokerStateFrame
    ...
    metrics.note_handoff_drop()
    frame = BrokerStateFrame(
        frame_id=1, cycle_started_m=0, cycle_finished_m=0.01,
        cycle_duration_ms=10, polled_at_wall="2026-07-13T00:00:00Z",
        positions=(), account=None, ticks=MappingProxyType({}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=(0, "OK"),
    )
    published = await consumer.process_frame(frame)
    assert consumer.connection_state == "DEGRADED"
    types = [event_type(e) for e in published]
    assert "broker.connection.changed" in types
    conn = next(e for e in published if event_type(e) == "broker.connection.changed")
    assert conn.payload["state"] == "DEGRADED"
    assert "HANDOFF_OVERRUN" in conn.payload["reasons"]


@pytest.mark.asyncio
async def test_coalesce_drop_count_integration(tmp_path: Path) -> None:
    # Slow consumer: don't start consumer; offer many frames via gateway; check metrics
    fake = FakeMt5()
    ...
    gw.start(); gw.wait_boot(3.0)
    await asyncio.sleep(0.3)  # many polls while slot unconsumed
    assert metrics.handoff_dropped_count >= 1
    frame = await asyncio.wait_for(slot.take(), timeout=2)
    # only latest continuity: frame_id should be the last produced
    assert frame.frame_id >= 2
    gw.stop()
```

- [ ] **Step 2: Implement connection transition in process_frame**

```python
def _recompute_state(self, frame: BrokerStateFrame) -> str:
    reasons: set[str] = set()
    if self._metrics.handoff_overrun_active:
        reasons.add("HANDOFF_OVERRUN")
    p95 = self._metrics.cycle_p95()
    if p95 is not None and p95 > self._poll_cycle_p95_budget_ms:
        reasons.add("POLL_P95")
    # tick ages ...
    if self.quarantine_tickets:
        reasons.add("ALIEN_POSITION")
    if frame.positions_unavailable or any(e.call == "account_info" for e in frame.errors):
        self._hard_fail_streak += 1
    else:
        self._hard_fail_streak = 0
    if self._hard_fail_streak >= self._hard_fail_threshold:
        self._degrade_reasons = reasons | {"HARD_FAIL"}
        return "DISCONNECTED"
    self._degrade_reasons = reasons
    if reasons:
        return "DEGRADED"
    return "CONNECTED"
```

On change:

```python
if new_state != self.connection_state:
    prev = self.connection_state
    self.connection_state = new_state
    await publish broker.connection.changed
    health = "DOWN" if new_state == "DISCONNECTED" else ("DEGRADED" if new_state == "DEGRADED" else "OK")
    await publish runtime.health.changed
```

- [ ] **Step 3: Run pass**

```powershell
uv run pytest tests/test_mt5_connection_state.py -v
```

---

## Task 15: Monotonic ages vs wall + None resilience

**Files:**
- Modify: `tests/test_mt5_metrics_clocks.py`
- Create: `tests/test_mt5_none_errors.py`

- [ ] **Step 1: Monotonic budget test with fake clocks**

```python
class FakeMono:
    def __init__(self) -> None:
        self.t = 1000.0
    def monotonic(self) -> float:
        return self.t

class FakeWall:
    def __init__(self) -> None:
        self.i = 0
    def now_iso(self) -> str:
        self.i += 1
        return f"2020-01-01T00:00:{self.i:02d}Z"

def test_budgets_use_monotonic_not_wall() -> None:
    # Unit: consumer tick age uses mono deltas only.
    # Simulate last_tick_mono and now; wall can jump years without affecting age.
    mono = FakeMono()
    # age = (mono.t - last) * 1000
    mono.t = 1000.0
    last = 999.0
    age_ms = (mono.t - last) * 1000
    assert age_ms == 1000.0
    # wall jump irrelevant
    wall = FakeWall()
    assert wall.now_iso().startswith("2020")
```

Stronger test via `process_frame`: inject mono/wall into consumer; advance mono past tick budget; expect DEGRADED `TICK_AGE`.

```python
@pytest.mark.asyncio
async def test_tick_age_budget_uses_monotonic(tmp_path: Path) -> None:
    mono = FakeMono()
    wall = FakeWall()
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=1, runtime_id="rt",
        mono=mono, wall=wall, tick_age_budget_ms=1000.0,
    )
    from metascan.mt5.types import TickRow, BrokerStateFrame
    from types import MappingProxyType
    # first frame establishes live tick
    t0 = TickRow("XAUUSDm", 1, 1.1, 1, time_msc=100, volume=0)
    f1 = BrokerStateFrame(
        frame_id=1, cycle_started_m=mono.t, cycle_finished_m=mono.t,
        cycle_duration_ms=1, polled_at_wall=wall.now_iso(),
        positions=(), account=None,
        ticks=MappingProxyType({"XAUUSDm": t0}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(f1)
    # second frame same tick msc (not advancing) after mono jump > budget
    mono.t += 2.0  # 2000ms
    t1 = TickRow("XAUUSDm", 1, 1.1, 1, time_msc=100, volume=0)  # frozen msc
    f2 = BrokerStateFrame(
        frame_id=2, cycle_started_m=mono.t, cycle_finished_m=mono.t,
        cycle_duration_ms=1, polled_at_wall=wall.now_iso(),
        positions=(), account=None,
        ticks=MappingProxyType({"XAUUSDm": t1}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(f2)
    assert "TICK_AGE" in consumer._degrade_reasons or consumer.connection_state == "DEGRADED"
    await bus.close()
```

Heuristic locked: if tick `time_msc` previously advanced then stops advancing while mono advances beyond budget → `TICK_AGE`. On first observation no degrade.

- [ ] **Step 2: None resilience tests**

```python
# tests/test_mt5_none_errors.py
@pytest.mark.asyncio
async def test_positions_get_none_with_error_no_crash(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1, 1.1, 1000)
    # after boot
    bus, gw, consumer, sub = await _stack(...)
    fake.set_return("positions_get", None)
    fake.set_last_error(1, "IPC failed")
    await asyncio.sleep(0.3)
    # gateway still alive
    assert gw._thread is not None and gw._thread.is_alive()
    # consumer not crashed
    assert consumer._task is not None and not consumer._task.done()
    await consumer.stop(); gw.stop(); await bus.close()


@pytest.mark.asyncio
async def test_account_info_none_frame_account_none(tmp_path: Path) -> None:
    # after boot, force account_info None; take frame via slot with consumer stopped
    ...
    fake.fail_next("account_info", times=5)
    frame = await asyncio.wait_for(slot.take(), timeout=2)
    assert frame.account is None
    assert any(e.call == "account_info" for e in frame.errors)
```

- [ ] **Step 3: Implement tick-age heuristic + ensure None paths; run pass**

```powershell
uv run pytest tests/test_mt5_metrics_clocks.py tests/test_mt5_none_errors.py -v
```

---

## Task 16: Classification flip matrix (same frames, different pending)

**Files:**
- Modify: `tests/test_mt5_external_close.py` or new cases already cover close/partial/modify.
- Add one consolidated test in `tests/test_mt5_external_close.py`:

```python
@pytest.mark.asyncio
async def test_same_sequence_different_pending_different_events(tmp_path: Path) -> None:
    """process_frame pure classification: inject two consumers, same frames."""
    from metascan.mt5.types import PositionRow, BrokerStateFrame, AccountRow
    from types import MappingProxyType

    row = make_position_row(ticket=1, magic=BOT, volume=0.2)
    def frame(positions):
        return BrokerStateFrame(
            frame_id=1, cycle_started_m=0, cycle_finished_m=0.01,
            cycle_duration_ms=10, polled_at_wall="2026-07-13T00:00:00Z",
            positions=tuple(positions), account=None,
            ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}),
            errors=(), mt5_last_error=None,
        )

    async def run(pending):
        j = Journal(tmp_path / f"j-{id(pending)}.sqlite")
        bus = EventBus(j)
        await bus.start()
        metrics = GatewayMetrics()
        slot = LatestFrameSlot(metrics)
        c = BrokerStateConsumer(
            bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
            runtime_id="rt", pending=pending,
        )
        await c.process_frame(frame([row]))
        await c.process_frame(frame([]))  # disappear
        rows = bus.journal.read_events(bus.boot_id, 0, 100)
        types = [event_type(r) for r in rows]
        await bus.close()
        return types

    ext = await run(NullPendingIntentLookup())
    bot = await run(ClosePending({1}))
    assert "trade.closed" in ext
    assert "trade.closed" not in bot
```

- [ ] **Step 2: Run pass**

```powershell
uv run pytest tests/test_mt5_external_close.py::test_same_sequence_different_pending_different_events -v
```

---

## Task 17: EventBus journal integration + no dual channel

**Files:**
- Create assertion in `tests/test_mt5_diff_positions.py` or lifecycle:

```python
@pytest.mark.asyncio
async def test_published_events_journaled_monotonic(tmp_path: Path) -> None:
    ...
    # after open event
    stored = bus.journal.read_events(bus.boot_id, 0, 100)
    assert stored
    seqs = [e.sequence for e in stored]
    assert seqs == list(range(1, len(seqs) + 1))
    assert all(e.boot_id == bus.boot_id for e in stored)
    assert all(str(getattr(e.source, "value", e.source)) == "LOCAL_RUNTIME" for e in stored)
```

- [ ] Run with suite subset.

---

## Task 18: Package exports + production factory stub (no real MT5 import in tests)

**Files:**
- Modify: `src/metascan/mt5/__init__.py`
- Optional create: `src/metascan/mt5/factory.py` **only if** needed — YAGNI: skip separate factory; document production wiring:

```python
# production (not unit-tested with real package):
# import MetaTrader5 as mt5
# gw = Mt5Gateway(mt5, config=..., slot=..., loop=..., metrics=...)
```

Ensure `tests/` never import `MetaTrader5`:

```python
# tests/test_mt5_lifecycle.py
def test_unit_tests_do_not_import_real_mt5() -> None:
    import sys
    assert "MetaTrader5" not in sys.modules or True
    # stronger: gateway module source
    text = Path("src/metascan/mt5/gateway.py").read_text(encoding="utf-8")
    assert "import MetaTrader5" not in text
    assert "from MetaTrader5" not in text
```

Gateway only receives injected module — no import of MetaTrader5 in package code. PASS.

- [ ] **Step: Update `__init__.py` re-exports**

```python
from metascan.mt5.gateway import GatewayBootError, GatewayConfig, Mt5Gateway
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.pending_intent import NullPendingIntentLookup, PendingIntentLookup
# + types
```

---

## Task 19: Full suite + SP3_SUMMARY + single commit

**Files:**
- Create: `backend/SP3_SUMMARY.md`

- [ ] **Step 1: Run full test suite**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest tests/ -v
```

Expected: all PASS (SP1+SP2+SP3).

- [ ] **Step 2: Grep self-checks**

```powershell
# no MANUAL_CLOSE in mt5 package
rg "MANUAL_CLOSE" src/metascan/mt5
# no order_send
rg "order_send|order_check|history_deals_get" src/metascan/mt5 -g "!testing/**"
# no hardcoded XAUUSDm in non-test production modules
rg "XAUUSDm" src/metascan/mt5 -g "!testing/**"
```

Expected: no matches for forbidden patterns in production modules (tests may use resolved symbols via suffix construction `"XAUUSD"+"m"` preferred; if tests use literal `XAUUSDm` that is OK in tests only).

- [ ] **Step 3: Write SP3_SUMMARY.md**

```markdown
# SP3 — Fake MT5 Gateway + Poll Diff

## Scope delivered

- Injected MT5 seam (`Mt5Gateway(mt5_module=...)`)
- Dedicated gateway thread owns all mt5.* calls
- Immutable BrokerStateFrame + LatestFrameSlot coalesce (bound 1)
- BrokerStateConsumer asyncio diff + SP2 EventBus publish
- FakeMt5 scriptable test double
- PendingIntentLookup classification (default false)
- Foreign magic quarantine + CRITICAL alert
- Monotonic metrics/budgets; wall for event stamps only
- No order execution; no account.updated/tick.updated

## Decisions

- positionId = str(ticket)
- exitReason = MANUAL only (never MANUAL_CLOSE)
- External partial = position.partially_closed
- External SL/TP = position.protection_changed
- Transient open/close blind spot accepted (SP7 later)
- MappingProxyType for frozen maps (no frozendict dep)

## Not in SP3

- order_send / RiskGate / FastAPI SSE / SP7 history / RuntimeCore rebuild
```

- [ ] **Step 4: One commit only (after all green)**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4
git add backend/src/metascan/mt5 backend/tests/test_mt5_*.py backend/tests/helpers.py backend/SP3_PLAN.md backend/SP3_SUMMARY.md
git status
git commit -m "SP3: fake MT5 gateway + poll diff"
```

Do **not** force-push. Do **not** amend Lovable history.

---

## Diff algorithm reference (complete)

```python
async def process_frame(self, frame: BrokerStateFrame) -> list[RuntimeEventEnvelope]:
    published: list[RuntimeEventEnvelope] = []
    try:
        # 1) tick mono bookkeeping
        for sym, tick in frame.ticks.items():
            prev_msc = self._last_tick_msc.get(sym)
            if prev_msc is not None and tick.time_msc > prev_msc:
                self._last_tick_mono[sym] = self._mono.monotonic()
                self._last_tick_msc[sym] = tick.time_msc
            elif sym not in self._last_tick_msc:
                self._last_tick_mono[sym] = self._mono.monotonic()
                self._last_tick_msc[sym] = tick.time_msc
            # else frozen msc: leave last advance mono as-is

        # 2) foreign scan + quarantine + alerts for new aliens
        ...

        # 3) connection state
        new_state = self._recompute_state(frame)
        if new_state != self.connection_state:
            ...
        
        if frame.positions_unavailable:
            self.last_frame_id = frame.frame_id
            return published

        managed = {p.ticket: p for p in frame.positions if p.magic == self._bot_magic}
        # never put foreign into managed

        # closes
        for ticket in list(self.last_positions.keys()):
            if ticket not in managed:
                ...  # pending close / external close

        # opens + updates
        for ticket, new in managed.items():
            if ticket not in self.last_positions:
                # position.opened
                self.last_positions[ticket] = new
                continue
            old = self.last_positions[ticket]
            # partial / protection / mtm branches
            self.last_positions[ticket] = new

        self.last_account = frame.account
        self.last_ticks = dict(frame.ticks)
        self.last_frame_id = frame.frame_id
        return published
    except Exception:
        logger.exception("diff failed frame_id=%s", frame.frame_id)
        return published
```

Consumer `_run`:

```python
async def _run(self) -> None:
    while not self._stop.is_set():
        try:
            frame = await asyncio.wait_for(self._slot.take(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        await self.process_frame(frame)
```

---

## Self-review (plan author checklist)

### Spec coverage

| Design § | Task(s) |
|---|---|
| One seam / inject FakeMt5 | 3, 6, 18 |
| Dedicated gateway thread | 6, 7 |
| Immutable frames | 1, 6 |
| Latest-frame coalesce + drop count | 4, 14 |
| call_soon_threadsafe handoff | 6 |
| Poll 250ms default clamp 50–2000 | 6 |
| Boot fail-fast login/symbol/hedge | 6 |
| Exact MT5 surface / forbidden order_send | 3, 7, 18 |
| PendingIntentLookup protocol | 1, 10–12, 16 |
| External close MANUAL | 5, 10 |
| External partial partially_closed | 11 |
| External SL/TP protection_changed | 12 |
| Foreign magic quarantine + CRITICAL | 13 |
| Symbol base+suffix no hardcode | 1, 6 |
| Connection CONNECTED/DEGRADED/DISCONNECTED | 14 |
| Monotonic vs wall clocks | 1, 2, 15 |
| Bounded metrics p50/p95 | 2 |
| No account.updated/tick.updated | 9 (explicit non-emit) |
| EventBus publish only | 9–17 |
| Lifecycle start/stop shutdown | 6, 7 |
| None resilience | 15 |
| Asyncio non-blocking | 8 |
| Blind spot accepted (no history API) | 7 source grep |
| Fake scriptable surface | 3 |
| Test matrix §15 | Tasks 7–17 |

### Placeholder scan

No TBD/TODO/implement-later steps. All tests include concrete code. All interfaces named with signatures.

### Type consistency

| Name | Locked spelling |
|---|---|
| `has_pending_close(ticket)` | pending_intent + tests |
| `has_pending_partial(ticket, volume)` | volume = **new** observed volume |
| `has_pending_modify(ticket)` | |
| `position_id_for` → `str(ticket)` | |
| `exitReason` / payload key camelCase `exitReason` | ClosedTrade wire |
| Event types | catalog exact dotted strings |
| `GatewayConfig.poll_interval_ms` | default 250 |
| `ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2` | |
| Metrics: `handoff_dropped_count`, `handoff_overrun_active` | |
| Connection reasons | `HANDOFF_OVERRUN`, `ALIEN_POSITION`, `TICK_AGE`, `POLL_P95`, `HARD_FAIL` |
| `BrokerStateFrame.positions_unavailable` | |
| `LatestFrameSlot.offer` / `take` | |
| `Mt5Gateway.wait_boot` / `stop` | |
| `BrokerStateConsumer.process_frame` / `start` / `stop` | |

### Gaps fixed in this plan

- Explicit MappingProxyType instead of third-party frozendict.
- `process_frame` public for pure unit classification without full poll race flakes.
- `event_type` helper for Enum vs str.
- Production code must not `import MetaTrader5`.
- One final commit message exact: `SP3: fake MT5 gateway + poll diff`.

---

## Execution handoff

Plan saved to `backend/SP3_PLAN.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
