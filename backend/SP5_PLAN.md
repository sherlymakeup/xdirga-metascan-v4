# SP5 Implementation Plan: RiskGate + Command Execution Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the full command pipeline: `POST /v4/commands` → ordered RiskGate → serialized gateway thread dispatch → outcome handling → `PendingIntentRegistry` → journaled transitions + SSE events. Replace SP4 stub with real execution path.

**Architecture:** `CommandPipeline` (single asyncio task) consumes from bounded `CommandQueue`, runs 8 ordered gates against a `GateContext` snapshot, dispatches via `Mt5CommandDispatcher` to the existing SP3 gateway thread, handles outcomes (success/rejection/timeout/disconnect), and publishes canonical events through `EventBus.publish_command_event`. `PendingIntentRegistry` implements the SP3 `PendingIntentLookup` Protocol.

**Tech Stack:** Python 3.12, stdlib `asyncio`/`concurrent.futures`/`dataclasses`, Pydantic SP1 models, SP2 EventBus/Journal, SP3 FakeMt5/gateway, pytest + pytest-asyncio. No new runtime deps.

**Commit policy (user override):** Do **not** commit per task. Run all RED→GREEN steps; only after full verification, **one** commit:

```bash
git add backend/src/metascan/pipeline backend/src/metascan/mt5/testing/fake_mt5.py backend/src/metascan/mt5/gateway.py backend/src/metascan/config.py backend/src/metascan/web/routers/commands.py backend/src/metascan/web/dependencies.py backend/tests/test_pipeline backend/SP5_PLAN.md backend/SP5_SUMMARY.md
git commit -m "SP5: RiskGate + command execution pipeline"
```

**Working directory for all commands:** `backend/` (unless noted).

**Run tests:**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest tests/test_pipeline/<name>.py -v
```

Full suite before commit:

```powershell
uv run pytest tests/ -v
```

**Do not touch:** frontend `src/`, SP1 contract field renames, SP2 journal/bus APIs (call only), SP3 consumer diff logic, SP4 SSE/handshake/health routers. Only extend: `gateway.py` (command queue), `fake_mt5.py` (order_send), `config.py` (RiskConfig), `commands.py` router (pipeline dispatch), `dependencies.py` (get_pipeline, get_risk_config).

---

## File Map

| Path | Responsibility | New/Modify |
|---|---|---|
| `src/metascan/pipeline/__init__.py` | Re-export public types | New |
| `src/metascan/pipeline/risk_config.py` | `RiskConfig` Pydantic model; loaded from `config.toml [risk]` | New |
| `src/metascan/pipeline/risk_gate.py` | `GateContext`, `GateResult`, 8 gate functions, `run_gates()` | New |
| `src/metascan/pipeline/command_queue.py` | `CommandQueue` (bounded `asyncio.Queue` wrapper), `CommandQueueFull` | New |
| `src/metascan/pipeline/pending_intent.py` | `PendingIntentRegistry` (real `PendingIntentLookup` impl) | New |
| `src/metascan/pipeline/dispatcher.py` | `Mt5CommandDispatcher`: submits Future to gateway thread queue | New |
| `src/metascan/pipeline/outcome_handler.py` | `OutcomeHandler`: COMPLETED/FAILED/TIMED_OUT/EXECUTION_UNKNOWN | New |
| `src/metascan/pipeline/command_pipeline.py` | `CommandPipeline` asyncio task (single consumer) | New |
| `src/metascan/mt5/gateway.py` | EXTENDED: `_command_queue`, `submit_command()` for SP5 dispatch | Modify |
| `src/metascan/mt5/testing/fake_mt5.py` | EXTENDED: `order_send`, `set_order_send_result`, `block_order_send`, `fail_order_send_disconnect` | Modify |
| `src/metascan/config.py` | EXTENDED: optional `[risk]` section → `RiskConfig` | Modify |
| `src/metascan/web/routers/commands.py` | EXTENDED: real pipeline dispatch (replace SP4 stub) | Modify |
| `src/metascan/web/dependencies.py` | EXTENDED: `get_pipeline`, `get_risk_config` | Modify |
| `tests/test_pipeline/__init__.py` | Package init | New |
| `tests/test_pipeline/conftest.py` | Fake bus, fake journal, fake gateway, fake risk config fixtures | New |
| `tests/test_pipeline/test_risk_config.py` | RiskConfig loads from toml; defaults; validation | New |
| `tests/test_pipeline/test_gate_kill_switch.py` | Gate 1 | New |
| `tests/test_pipeline/test_gate_runtime_state.py` | Gate 2 | New |
| `tests/test_pipeline/test_gate_freshness.py` | Gate 3 | New |
| `tests/test_pipeline/test_gate_hard_sl.py` | Gate 4 | New |
| `tests/test_pipeline/test_gate_sizing.py` | Gate 5 | New |
| `tests/test_pipeline/test_gate_spread.py` | Gate 6 | New |
| `tests/test_pipeline/test_gate_exposure.py` | Gate 7 | New |
| `tests/test_pipeline/test_gate_freeze.py` | Gate 8 | New |
| `tests/test_pipeline/test_gate_order.py` | Gates run 1-8; first failure short-circuits | New |
| `tests/test_pipeline/test_gate_safety_skips.py` | `emergencyKill` bypasses gates 1-3 | New |
| `tests/test_pipeline/test_pending_intent.py` | register/clear/has_pending_*; EXECUTION_UNKNOWN retains | New |
| `tests/test_pipeline/test_pipeline_happy.py` | Full happy path: PREPARED→ACCEPTED→COMPLETED | New |
| `tests/test_pipeline/test_pipeline_broker_reject.py` | ACCEPTED→FAILED(BROKER_REJECTED) | New |
| `tests/test_pipeline/test_pipeline_timeout.py` | Timeout→TIMED_OUT; late result→EXECUTION_UNKNOWN | New |
| `tests/test_pipeline/test_pipeline_disconnect.py` | Disconnect mid-call→EXECUTION_UNKNOWN | New |
| `tests/test_pipeline/test_pipeline_idempotency.py` | Same idempotencyKey returns same record | New |
| `tests/test_pipeline/test_pipeline_unsupported.py` | Unsupported kind → accepted→FAILED(UNSUPPORTED_COMMAND) | New |
| `tests/test_pipeline/test_mutation_inflight_slo.py` | Entity excluded from SLO while inflight | New |
| `tests/test_pipeline/test_transition_sequence.py` | transition.sequence == event.sequence invariant | New |
| `tests/test_pipeline/test_close_exit_mapping.py` | exitReason MANUAL / KILL_SWITCH per command kind | New |
| `tests/test_pipeline/test_execution_unknown_no_retry.py` | EXECUTION_UNKNOWN is terminal; not re-queued | New |

---

## Locked Interfaces (implement exactly)

### RiskConfig

```python
# src/metascan/pipeline/risk_config.py
from pydantic import BaseModel, Field

class RiskConfig(BaseModel):
    max_open_positions: int = 5
    max_volume_per_symbol: float = 1.0
    max_daily_loss_pct: float = 0.05
    spread_max_multiple: float = 3.0
    spread_median_window: int = 20
    tick_age_budget_ms: int = 1000
    account_age_budget_ms: int = 2000
    gateway_timeout_s: float = 10.0
```

### GateContext & GateResult

```python
# src/metascan/pipeline/risk_gate.py
from dataclasses import dataclass
from metascan.mt5.types import AccountRow, PositionRow, TickRow, SymbolMeta

@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reason: str | None = None

@dataclass(frozen=True, slots=True)
class GateContext:
    command_kind: str
    target_symbol: str | None
    target_ticket: int | None
    requested_volume: float | None
    requested_sl: float | None
    requested_tp: float | None
    requested_price: float | None
    kill_switch_engaged: bool
    runtime_state: str
    safe_mode_active: bool
    positions: tuple[PositionRow, ...]
    account: AccountRow | None
    ticks: dict[str, TickRow]
    symbol_meta: dict[str, SymbolMeta]
    tick_ages_ms: dict[str, float]
    account_age_ms: float
    spread_samples: dict[str, list[float]]
    day_start_balance: float
    daily_realized_pnl: float
    trading_halt: bool
    inflight_entities: dict[str, str]  # entity_id → command_id
```

### CommandQueue

```python
# src/metascan/pipeline/command_queue.py
import asyncio
from metascan.contract.models import RuntimeCommandStatus

class CommandQueueFull(RuntimeError):
    pass

class CommandQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._queue: asyncio.Queue[RuntimeCommandStatus] = asyncio.Queue(maxsize=maxsize)

    def put_nowait(self, item: RuntimeCommandStatus) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            raise CommandQueueFull("Command queue full")

    async def get(self) -> RuntimeCommandStatus:
        return await self._queue.get()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()
```

### PendingIntentRegistry

```python
# src/metascan/pipeline/pending_intent.py
from dataclasses import dataclass, field

@dataclass
class _Intent:
    command_id: str
    kind: str  # "close" | "partial" | "modify"
    volume: float | None = None

class PendingIntentRegistry:
    def __init__(self) -> None:
        self._intents: dict[int, _Intent] = {}
        self._retained: set[int] = set()  # tickets retained for EXECUTION_UNKNOWN

    def register_close(self, ticket: int, command_id: str) -> None:
        self._intents[ticket] = _Intent(command_id, "close")

    def register_partial(self, ticket: int, volume: float, command_id: str) -> None:
        self._intents[ticket] = _Intent(command_id, "partial", volume)

    def register_modify(self, ticket: int, command_id: str) -> None:
        self._intents[ticket] = _Intent(command_id, "modify")

    def clear(self, ticket: int) -> None:
        self._intents.pop(ticket, None)
        self._retained.discard(ticket)

    def retain_for_reconciliation(self, ticket: int) -> None:
        self._retained.add(ticket)

    def has_pending_close(self, ticket: int) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "close"

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "partial"

    def has_pending_modify(self, ticket: int) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "modify"
```

### Mt5CommandDispatcher

```python
# src/metascan/pipeline/dispatcher.py
import asyncio
import concurrent.futures
from typing import Any, Callable

class Mt5CommandDispatcher:
    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    async def dispatch(
        self,
        callable_fn: Callable[[], Any],
        *,
        timeout_s: float,
    ) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, callable_fn)
        # Submit to gateway's command queue so it runs on the gateway thread
        # Await with timeout; do NOT cancel underlying future on timeout
        try:
            result = await asyncio.wait_for(
                asyncio.wrap_future(future) if isinstance(future, concurrent.futures.Future) else future,
                timeout=timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            raise  # caller handles transition to TIMED_OUT
```

### FakeMt5 SP5 Extensions (additive)

```python
# Additions to src/metascan/mt5/testing/fake_mt5.py

# New instance state in __init__:
#   self._order_send_results: list[tuple[int, int]] = []  # (ticket, retcode)
#   self._order_send_block_s: float | None = None
#   self._order_send_disconnect: bool = False

def order_send(self, request: Any) -> SimpleNamespace | None:
    if not self._touch("order_send"):
        return None
    if self._order_send_disconnect:
        self._order_send_disconnect = False
        raise ConnectionError("broker disconnect mid-call")
    if self._order_send_block_s is not None:
        time.sleep(self._order_send_block_s)
        self._order_send_block_s = None
    if self._order_send_results:
        ticket, retcode = self._order_send_results.pop(0)
        return SimpleNamespace(retcode=retcode, order=ticket, comment="")
    return SimpleNamespace(retcode=10009, order=99999, comment="done")

def set_order_send_result(self, ticket: int, retcode: int) -> None:
    self._order_send_results.append((ticket, retcode))

def block_order_send(self, seconds: float) -> None:
    self._order_send_block_s = seconds

def fail_order_send_disconnect(self) -> None:
    self._order_send_disconnect = True
```

### Gateway SP5 Extension

```python
# Addition to Mt5Gateway: a thread-safe command queue for order_send calls
# Uses queue.Queue consumed on the gateway thread between poll cycles

import queue
import concurrent.futures

# In __init__:
#   self._cmd_queue: queue.Queue[tuple[Callable, concurrent.futures.Future]] = queue.Queue()

# New method:
def submit_command(self, fn: Callable[[], Any]) -> concurrent.futures.Future:
    fut: concurrent.futures.Future = concurrent.futures.Future()
    self._cmd_queue.put((fn, fut))
    return fut

# In _poll_loop, between cycles: drain _cmd_queue and execute each on gateway thread
def _drain_commands(self) -> None:
    while True:
        try:
            fn, fut = self._cmd_queue.get_nowait()
        except queue.Empty:
            break
        try:
            result = fn()
            fut.set_result(result)
        except BaseException as exc:
            fut.set_exception(exc)
```

---

## 8 Gates — Order, Reasons, and Transitions

| # | Gate | Applies to | Reason on fail | Transition |
|---|---|---|---|---|
| 1 | `KillSwitchGate` | All order-producing commands | `KILL_SWITCH_ENGAGED` | SUBMITTING→FAILED |
| 2 | `RuntimeStateGate` | All commands (runtime readiness) | `RUNTIME_NOT_READY` or `SAFE_MODE_ACTIVE` | SUBMITTING→FAILED |
| 3 | `DataFreshnessGate` | Order-producing commands | `STALE_TICK` or `STALE_ACCOUNT` | SUBMITTING→FAILED |
| 4 | `HardSlGate` | Open-type commands only | `MISSING_HARD_SL` | SUBMITTING→FAILED |
| 5 | `SizingGate` | Commands with volume/price params | `VOLUME_OUT_OF_RANGE`, `PRICE_VIOLATES_STOPS_LEVEL`, `PRICE_VIOLATES_FREEZE_LEVEL`, `SIZING_FLOOR_REJECTION` | SUBMITTING→FAILED |
| 6 | `SpreadGuardGate` | Order-opening commands | `SPREAD_TOO_WIDE` | SUBMITTING→FAILED |
| 7 | `ExposureGate` | Order-opening commands | `MAX_POSITIONS_REACHED`, `MAX_VOLUME_PER_SYMBOL`, `DAILY_LOSS_LIMIT_BREACHED` | SUBMITTING→FAILED |
| 8 | `FreezeGate` | Modify/partial-close commands | `PRICE_VIOLATES_FREEZE_LEVEL` | SUBMITTING→FAILED |

**Safety skips:** `runtime.emergencyKill` bypasses Gates 1, 2, 3 entirely.

**Short-circuit:** First gate failure stops; no subsequent gates run.

**Gate 7 side-effect:** `DAILY_LOSS_LIMIT_BREACHED` also sets `trading_halt = True` in runtime state.

**Gate 5 downward floor:** If computed volume (rounded to `volume_step`) < `volume_min`, reject with `SIZING_FLOOR_REJECTION`. Never silently change requested size.

**Gate 6 skip condition:** If < 3 spread samples available, gate is skipped (not enough data).

---

## Unsupported Commands

Commands whose `kind` is in `RUNTIME_COMMAND_KINDS` but not implemented in SP5:

**Implemented:** `position.close`, `position.closePartial`, `position.modifyProtection`, `position.closeAll`, `order.cancel`, `runtime.emergencyKill`

**Unsupported (accepted → FAILED):** `runtime.start`, `runtime.pause`, `runtime.resume`, `runtime.stop`, `runtime.restart`, `runtime.reconnectBroker`, `runtime.reconcile`, `runtime.disableEntries`, `runtime.enableEntries`, `strategy.pause`, `strategy.resume`, `strategy.disable`, `order.cancelAll`, `position.management.pause`, `position.management.resume`, `breaker.reset`, `alert.acknowledge`, `incident.acknowledge`, `config.validate`, `config.apply`, `config.rollback`

**Unknown kind** (not in `RUNTIME_COMMAND_KINDS`): 422 Unprocessable Entity, no journal write.

---

## Close Exit Mapping

| Command kind | exitReason |
|---|---|
| `position.close` (operator) | `MANUAL` |
| `runtime.emergencyKill` (flatten) | `KILL_SWITCH` |
| `position.closePartial` final fill | `PARTIAL_FINAL` |

SP5 only emits `MANUAL` and `KILL_SWITCH`. Others reserved for future slices.

---

## Concurrency & Idempotency

1. **Single consumer:** `CommandPipeline` is a single asyncio task. All gate evaluation and dispatch happen serially.
2. **Serialized gateway mutations:** All `order_send` calls go through `Mt5Gateway.submit_command()` → gateway thread's `_cmd_queue`. Same thread as poll cycles.
3. **Idempotency:** `CommandRouter` checks `get_command_by_idempotency_key()` before creating. If found, returns existing record. No new journal write.
4. **Future timeout:** `asyncio.wait_for` wraps the Future. On timeout, underlying Future is NOT cancelled.
5. **`_inflight` dict:** `entity_id → command_id`. Written on ACCEPTED, cleared on terminal. Excludes entity from DataFreshnessGate and SLO.

---

## Task 1: RiskConfig + config.py extension

**Files:**
- Create: `src/metascan/pipeline/__init__.py`
- Create: `src/metascan/pipeline/risk_config.py`
- Modify: `src/metascan/config.py` (optional `[risk]` section)
- Create: `tests/test_pipeline/__init__.py`
- Create: `tests/test_pipeline/conftest.py`
- Create: `tests/test_pipeline/test_risk_config.py`

- [ ] **Step 1: Write failing test** — `test_risk_config.py`

```python
# tests/test_pipeline/test_risk_config.py
from __future__ import annotations

import pytest
from metascan.pipeline.risk_config import RiskConfig


def test_defaults() -> None:
    rc = RiskConfig()
    assert rc.max_open_positions == 5
    assert rc.max_volume_per_symbol == 1.0
    assert rc.max_daily_loss_pct == 0.05
    assert rc.spread_max_multiple == 3.0
    assert rc.spread_median_window == 20
    assert rc.tick_age_budget_ms == 1000
    assert rc.account_age_budget_ms == 2000
    assert rc.gateway_timeout_s == 10.0


def test_custom_values() -> None:
    rc = RiskConfig(max_open_positions=10, gateway_timeout_s=5.0)
    assert rc.max_open_positions == 10
    assert rc.gateway_timeout_s == 5.0


def test_config_loads_risk_section(tmp_path) -> None:
    from metascan.config import load_config

    toml = tmp_path / "config.toml"
    toml.write_text(
        '[runtime]\n'
        'runtime_name = "test"\n'
        'protocol_id = "xdirga-v4"\n'
        'protocol_version = "4.0.0"\n'
        'schema_version = "4.0.0"\n'
        'broker_provider = "EXNESS"\n'
        'broker_environment = "TRIAL"\n'
        'execution_semantics = "LIVE"\n'
        '\n'
        '[risk]\n'
        'max_open_positions = 3\n'
        'gateway_timeout_s = 7.5\n',
        encoding="utf-8",
    )
    cfg = load_config(config_path=toml, env_path=tmp_path / ".env.missing")
    risk_raw = cfg.model_extra.get("risk") if cfg.model_extra else None
    assert risk_raw is not None
    rc = RiskConfig(**risk_raw)
    assert rc.max_open_positions == 3
    assert rc.gateway_timeout_s == 7.5
    assert rc.max_daily_loss_pct == 0.05  # default
```

- [ ] **Step 2: Run — expect fail** (import error)

```powershell
uv run pytest tests/test_pipeline/test_risk_config.py -v
```

- [ ] **Step 3: Implement**

Create `src/metascan/pipeline/__init__.py` (empty).
Create `src/metascan/pipeline/risk_config.py` with locked `RiskConfig` Pydantic model.
Create `tests/test_pipeline/__init__.py` (empty).
Create `tests/test_pipeline/conftest.py` (empty initially; will grow).

`config.py` already has `extra="allow"` on `AppConfig`, so `[risk]` section flows through to `model_extra`. No code change needed in `config.py` — the test validates this.

- [ ] **Step 4: Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_risk_config.py -v
```

---

## Task 2: GateContext, GateResult, and individual gates (pure functions)

**Files:**
- Create: `src/metascan/pipeline/risk_gate.py`
- Create: `tests/test_pipeline/test_gate_kill_switch.py`
- Create: `tests/test_pipeline/test_gate_runtime_state.py`
- Create: `tests/test_pipeline/test_gate_freshness.py`
- Create: `tests/test_pipeline/test_gate_hard_sl.py`
- Create: `tests/test_pipeline/test_gate_sizing.py`
- Create: `tests/test_pipeline/test_gate_spread.py`
- Create: `tests/test_pipeline/test_gate_exposure.py`
- Create: `tests/test_pipeline/test_gate_freeze.py`

### Step 2.1: Gate 1 — KillSwitchGate

- [ ] **RED: Write test**

```python
# tests/test_pipeline/test_gate_kill_switch.py
from __future__ import annotations
from tests.test_pipeline.conftest import make_gate_context
from metascan.pipeline.risk_gate import gate_kill_switch


def test_blocks_when_killed() -> None:
    ctx = make_gate_context(kill_switch_engaged=True, command_kind="position.close")
    r = gate_kill_switch(ctx)
    assert not r.passed
    assert r.reason == "KILL_SWITCH_ENGAGED"


def test_passes_when_not_killed() -> None:
    ctx = make_gate_context(kill_switch_engaged=False, command_kind="position.close")
    r = gate_kill_switch(ctx)
    assert r.passed


def test_emergency_kill_always_passes() -> None:
    ctx = make_gate_context(kill_switch_engaged=True, command_kind="runtime.emergencyKill")
    r = gate_kill_switch(ctx)
    assert r.passed
```

- [ ] **Run — fail**

```powershell
uv run pytest tests/test_pipeline/test_gate_kill_switch.py -v
```

- [ ] **GREEN: Implement `gate_kill_switch` in `risk_gate.py`**

Gate function signature: `def gate_kill_switch(ctx: GateContext) -> GateResult`

Also implement `GateContext`, `GateResult` dataclasses. Add `make_gate_context` factory to `conftest.py` returning a `GateContext` with sensible defaults.

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_gate_kill_switch.py -v
```

### Step 2.2: Gate 2 — RuntimeStateGate

- [ ] **RED: Write `test_gate_runtime_state.py`**

Tests: READY passes; DEGRADED passes for non-order-producing; KILLED blocks with `RUNTIME_NOT_READY`; `safe_mode_active` blocks with `SAFE_MODE_ACTIVE`; `emergencyKill` bypasses entirely.

- [ ] **GREEN: Implement `gate_runtime_state` in `risk_gate.py`**

- [ ] **Run — pass**

### Step 2.3: Gate 3 — DataFreshnessGate

- [ ] **RED: Write `test_gate_freshness.py`**

Tests: stale tick → `STALE_TICK`; stale account → `STALE_ACCOUNT`; fresh passes; `emergencyKill` bypasses; non-order-producing commands skip gate; inflight entities excluded.

- [ ] **GREEN: Implement `gate_data_freshness`**

- [ ] **Run — pass**

### Step 2.4: Gate 4 — HardSlGate

- [ ] **RED: Write `test_gate_hard_sl.py`**

Tests: open command without SL → `MISSING_HARD_SL`; with SL passes; close commands skip gate.

- [ ] **GREEN: Implement `gate_hard_sl`**

- [ ] **Run — pass**

### Step 2.5: Gate 5 — SizingGate

- [ ] **RED: Write `test_gate_sizing.py`**

Tests: volume below min → `VOLUME_OUT_OF_RANGE`; above max → same; invalid step → same; floor rejection (rounded below min) → `SIZING_FLOOR_REJECTION`; stops level violation → `PRICE_VIOLATES_STOPS_LEVEL`; freeze level → `PRICE_VIOLATES_FREEZE_LEVEL`; valid params pass.

- [ ] **GREEN: Implement `gate_sizing`**

Sizing algorithm:
- Check `volume >= volume_min` and `volume <= volume_max`.
- Check `volume % volume_step` tolerance (floating point: `abs(volume / volume_step - round(volume / volume_step)) * volume_step < volume_step * 0.01`).
- If volume would round down below `volume_min`, reject with `SIZING_FLOOR_REJECTION`.
- Check stops_level: `|price - sl|` and `|price - tp|` in points ≥ `trade_stops_level`.
- Check freeze_level at sizing time.

- [ ] **Run — pass**

### Step 2.6: Gate 6 — SpreadGuardGate

- [ ] **RED: Write `test_gate_spread.py`**

Tests: spread > 3x median → `SPREAD_TOO_WIDE`; normal spread passes; < 3 samples → gate skipped (passes).

- [ ] **GREEN: Implement `gate_spread_guard`**

Rolling median: sort samples, pick middle. Compare `current_spread > spread_max_multiple × median`.

- [ ] **Run — pass**

### Step 2.7: Gate 7 — ExposureGate

- [ ] **RED: Write `test_gate_exposure.py`**

Tests: max positions reached → `MAX_POSITIONS_REACHED`; max volume per symbol → `MAX_VOLUME_PER_SYMBOL`; daily loss breached → `DAILY_LOSS_LIMIT_BREACHED` + `trading_halt` side-effect; all within limits passes.

- [ ] **GREEN: Implement `gate_exposure`**

Daily loss check: `daily_realized_pnl + Σ(position.profit) < -(max_daily_loss_pct × day_start_balance)`.

Note: `trading_halt` is a side-effect. The gate returns a `GateResult` with `passed=False` and the pipeline sets `trading_halt=True` on runtime state when reason is `DAILY_LOSS_LIMIT_BREACHED`.

- [ ] **Run — pass**

### Step 2.8: Gate 8 — FreezeGate

- [ ] **RED: Write `test_gate_freeze.py`**

Tests: price within freeze zone of position → `PRICE_VIOLATES_FREEZE_LEVEL`; outside passes; freeze_level=0 → gate skipped.

- [ ] **GREEN: Implement `gate_freeze`**

- [ ] **Run — pass**

---

## Task 3: Gate ordering + safety skips

**Files:**
- Create: `tests/test_pipeline/test_gate_order.py`
- Create: `tests/test_pipeline/test_gate_safety_skips.py`

- [ ] **RED: Write `test_gate_order.py`**

Tests: gates run in order 1-8; when gate 1 fails, gate 2+ do NOT run (verify via a context that would fail gate 3 but gate 1 fails first).

Implement `run_gates(ctx: GateContext, risk_config: RiskConfig) -> GateResult` in `risk_gate.py` that calls each gate function in order, short-circuiting on first failure.

```python
ORDER_PRODUCING_KINDS = frozenset({
    "position.close", "position.closePartial", "position.modifyProtection",
    "position.closeAll", "order.cancel", "runtime.emergencyKill",
})

GATE_ORDER = [
    gate_kill_switch,
    gate_runtime_state,
    gate_data_freshness,
    gate_hard_sl,
    gate_sizing,
    gate_spread_guard,
    gate_exposure,
    gate_freeze,
]

def run_gates(ctx: GateContext, config: RiskConfig) -> GateResult:
    for gate_fn in GATE_ORDER:
        result = gate_fn(ctx, config)  # config passed for threshold access
        if not result.passed:
            return result
    return GateResult(passed=True)
```

- [ ] **RED: Write `test_gate_safety_skips.py`**

Tests: `runtime.emergencyKill` bypasses gates 1, 2, 3 (even when kill switch engaged, runtime not ready, stale ticks).

- [ ] **GREEN: Implement; run pass**

```powershell
uv run pytest tests/test_pipeline/test_gate_order.py tests/test_pipeline/test_gate_safety_skips.py -v
```

---

## Task 4: PendingIntentRegistry

**Files:**
- Create: `src/metascan/pipeline/pending_intent.py`
- Create: `tests/test_pipeline/test_pending_intent.py`

- [ ] **RED: Write `test_pending_intent.py`**

```python
# tests/test_pipeline/test_pending_intent.py
from metascan.pipeline.pending_intent import PendingIntentRegistry


def test_register_close_and_query() -> None:
    r = PendingIntentRegistry()
    r.register_close(1001, "cmd-1")
    assert r.has_pending_close(1001) is True
    assert r.has_pending_modify(1001) is False
    assert r.has_pending_close(9999) is False


def test_register_partial() -> None:
    r = PendingIntentRegistry()
    r.register_partial(1001, 0.05, "cmd-2")
    assert r.has_pending_partial(1001, 0.05) is True
    assert r.has_pending_close(1001) is False


def test_register_modify() -> None:
    r = PendingIntentRegistry()
    r.register_modify(1001, "cmd-3")
    assert r.has_pending_modify(1001) is True


def test_clear_removes() -> None:
    r = PendingIntentRegistry()
    r.register_close(1001, "cmd-1")
    r.clear(1001)
    assert r.has_pending_close(1001) is False


def test_retain_for_reconciliation_keeps_intent() -> None:
    r = PendingIntentRegistry()
    r.register_close(1001, "cmd-1")
    r.retain_for_reconciliation(1001)
    assert r.has_pending_close(1001) is True
    # clear after reconciliation resolves
    r.clear(1001)
    assert r.has_pending_close(1001) is False


def test_implements_pending_intent_lookup_protocol() -> None:
    from metascan.mt5.pending_intent import PendingIntentLookup
    r = PendingIntentRegistry()
    assert isinstance(r, PendingIntentLookup)  # structural typing via Protocol
```

Note: Protocol structural check — `isinstance` only works if Protocol uses `runtime_checkable`. If not, test with duck typing: call all three methods and verify no AttributeError.

- [ ] **GREEN: Implement `pending_intent.py`**

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pending_intent.py -v
```

---

## Task 5: FakeMt5 extensions (order_send)

**Files:**
- Modify: `src/metascan/mt5/testing/fake_mt5.py`

- [ ] **RED: Write test in `test_pipeline/conftest.py` or as standalone check**

Add to `tests/test_pipeline/conftest.py` a helper and a quick smoke test that `FakeMt5.order_send` works:

```python
# In test_pipeline/conftest.py — smoke test
def test_fake_order_send_default() -> None:
    from metascan.mt5.testing.fake_mt5 import FakeMt5
    f = FakeMt5()
    f.initialize()
    r = f.order_send({})
    assert r is not None
    assert r.retcode == 10009


def test_fake_order_send_scripted() -> None:
    from metascan.mt5.testing.fake_mt5 import FakeMt5
    f = FakeMt5()
    f.initialize()
    f.set_order_send_result(ticket=42, retcode=10006)
    r = f.order_send({})
    assert r.retcode == 10006
    assert r.order == 42


def test_fake_order_send_disconnect() -> None:
    import pytest
    from metascan.mt5.testing.fake_mt5 import FakeMt5
    f = FakeMt5()
    f.initialize()
    f.fail_order_send_disconnect()
    with pytest.raises(ConnectionError):
        f.order_send({})
```

- [ ] **GREEN: Extend `FakeMt5`**

Add `_order_send_results`, `_order_send_block_s`, `_order_send_disconnect` to `__init__`. Add `order_send()`, `set_order_send_result()`, `block_order_send()`, `fail_order_send_disconnect()` methods.

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/conftest.py -v -k "test_fake"
```

Verify existing SP3 tests still pass:

```powershell
uv run pytest tests/test_mt5_fake_scriptable.py -v
```

---

## Task 6: Gateway extension (command queue on gateway thread)

**Files:**
- Modify: `src/metascan/mt5/gateway.py`

- [ ] **RED: Write test**

```python
# tests/test_pipeline/test_gateway_cmd_queue.py (or add to conftest.py)
import asyncio
import pytest
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.mt5.gateway import Mt5Gateway, GatewayConfig
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from tests.helpers import default_account, default_symbol_info


@pytest.mark.asyncio
async def test_submit_command_runs_on_gateway_thread() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account())
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    cfg = GatewayConfig(
        login=123456, password="x", server="s",
        symbol_suffix="m", watchlist_bases=("XAUUSD",),
        bot_magic=240101, poll_interval_ms=50,
    )
    gw = Mt5Gateway(fake, config=cfg, slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)
    try:
        import threading
        result_holder = {}

        def cmd():
            result_holder["tid"] = threading.get_ident()
            return 42

        fut = gw.submit_command(cmd)
        val = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=5.0)
        assert val == 42
        assert result_holder["tid"] == gw._thread.ident
    finally:
        gw.stop()
```

- [ ] **GREEN: Extend `Mt5Gateway`**

Add `import queue, concurrent.futures` to gateway.py. Add `self._cmd_queue = queue.Queue()` in `__init__`. Add `submit_command()`. Add `_drain_commands()`. Call `_drain_commands()` in `_poll_loop` at the top of each iteration (before `_one_cycle`).

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_gateway_cmd_queue.py -v
```

Verify existing gateway tests still pass:

```powershell
uv run pytest tests/test_mt5_gateway_thread.py tests/test_mt5_boot_verify.py -v
```

---

## Task 7: CommandQueue + CommandPipeline scaffolding

**Files:**
- Create: `src/metascan/pipeline/command_queue.py`
- Create: `src/metascan/pipeline/dispatcher.py`
- Create: `src/metascan/pipeline/outcome_handler.py`
- Create: `src/metascan/pipeline/command_pipeline.py`

- [ ] **Step 1: RED — Write `test_pipeline_happy.py`**

```python
# tests/test_pipeline/test_pipeline_happy.py
import asyncio
import pytest
from pathlib import Path
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.mt5.gateway import Mt5Gateway, GatewayConfig
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.contract.models import RuntimeCommandStatus
from tests.helpers import default_account, default_symbol_info


@pytest.mark.asyncio
async def test_happy_path_close_completes(tmp_path: Path) -> None:
    j = Journal(tmp_path / "test.db")
    bus = EventBus(j)
    await bus.start()
    fake = FakeMt5()
    fake.set_account(**default_account())
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    fake.set_order_send_result(ticket=1001, retcode=10009)
    fake.set_positions([{
        "ticket": 1001, "symbol": "XAUUSDm", "magic": 240101,
        "volume": 0.1, "price_open": 2300.0, "price_current": 2301.0,
        "sl": 2290.0, "tp": 2320.0, "profit": 10.0, "swap": 0.0,
        "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 1001,
        "comment": "",
    }])
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    cfg = GatewayConfig(
        login=123456, password="x", server="s",
        symbol_suffix="m", watchlist_bases=("XAUUSD",),
        bot_magic=240101, poll_interval_ms=50,
    )
    gw = Mt5Gateway(fake, config=cfg, slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)

    risk_config = RiskConfig()
    pending = PendingIntentRegistry()
    sub = await bus.subscribe("test-sub", maxsize=256)

    pipeline = CommandPipeline(
        bus=bus,
        gateway=gw,
        risk_config=risk_config,
        pending=pending,
        bot_magic=240101,
        runtime_id="rt-test",
    )
    pipeline.start()

    status = RuntimeCommandStatus(
        command_id="cmd-1",
        client_request_id="cr-1",
        correlation_id="cor-1",
        idempotency_key="idem-1",
        kind="position.close",
        target_id="1001",
        state="PREPARED",
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:00Z",
    )
    pipeline.enqueue(status)

    # Collect events
    events = []
    for _ in range(10):
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=2.0)
            if hasattr(ev, "type"):
                events.append(ev)
                type_val = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
                if type_val in ("command.completed", "command.failed"):
                    break
        except asyncio.TimeoutError:
            break

    await pipeline.stop()
    gw.stop()
    await bus.close()

    types = [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events]
    assert "command.completed" in types
```

- [ ] **Step 2: Implement CommandQueue, Dispatcher, OutcomeHandler, CommandPipeline**

**`CommandPipeline` core loop:**

```python
class CommandPipeline:
    def __init__(self, *, bus, gateway, risk_config, pending, bot_magic, runtime_id, ...):
        self._bus = bus
        self._gateway = gateway
        self._risk_config = risk_config
        self._pending = pending
        self._queue = CommandQueue()
        self._inflight: dict[str, str] = {}  # entity_id → command_id
        self._task = None
        self._stop = asyncio.Event()
        # Runtime state (mutable, updated externally):
        self._kill_switch_engaged = False
        self._runtime_state = "READY"
        self._safe_mode_active = False
        self._trading_halt = False
        self._day_start_balance = 0.0
        self._daily_realized_pnl = 0.0
        self._spread_samples: dict[str, list[float]] = {}

    def enqueue(self, status: RuntimeCommandStatus) -> None:
        self._queue.put_nowait(status)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except: pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                status = await asyncio.wait_for(self._queue._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await self._process(status)

    async def _process(self, status: RuntimeCommandStatus) -> None:
        # 1. Check unsupported
        # 2. Transition PREPARED → SUBMITTING (journal, no SSE)
        # 3. Build GateContext
        # 4. run_gates()
        # 5a. Gate fail → SUBMITTING → FAILED
        # 5b. All pass → SUBMITTING → ACCEPTED
        #     → register pending intent
        #     → dispatch to gateway thread
        #     → await result with timeout
        #     → handle outcome (COMPLETED/FAILED/TIMED_OUT/EXECUTION_UNKNOWN)
        ...
```

- [ ] **Step 3: Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_happy.py -v
```

---

## Task 8: Broker rejection path

**Files:**
- Create: `tests/test_pipeline/test_pipeline_broker_reject.py`

- [ ] **RED: Write test**

Same setup as happy path but `fake.set_order_send_result(ticket=1001, retcode=10006)`. Expect `command.failed` with reason `BROKER_REJECTED`.

- [ ] **GREEN: Already implemented in OutcomeHandler** (retcode != 10009 → FAILED)

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_broker_reject.py -v
```

---

## Task 9: Timeout path

**Files:**
- Create: `tests/test_pipeline/test_pipeline_timeout.py`

- [ ] **RED: Write test**

```python
# Use fake.block_order_send(seconds=15.0) with risk_config.gateway_timeout_s=0.5
# Expect: command.timed_out with reason GATEWAY_TIMEOUT
# Then: if late result arrives → command.execution_unknown with reason OUTCOME_AMBIGUOUS
```

- [ ] **GREEN: Implement OutcomeHandler late-result watcher**

On timeout:
1. Transition ACCEPTED → TIMED_OUT (reason: GATEWAY_TIMEOUT)
2. Start background task watching the un-cancelled Future
3. If Future resolves later: emit `command.execution_unknown` (reason: OUTCOME_AMBIGUOUS)
4. PendingIntentRegistry retains entry + `retain_for_reconciliation(ticket)`

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_timeout.py -v
```

---

## Task 10: Disconnect path

**Files:**
- Create: `tests/test_pipeline/test_pipeline_disconnect.py`

- [ ] **RED: Write test**

```python
# fake.fail_order_send_disconnect() → ConnectionError
# Expect: command.execution_unknown with reason BROKER_DISCONNECT_MID_CALL
# + reconciliation.issue.detected with severity=HIGH
```

- [ ] **GREEN: Already handled in OutcomeHandler** (exception from Future → EXECUTION_UNKNOWN)

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_disconnect.py -v
```

---

## Task 11: Idempotency integration

**Files:**
- Create: `tests/test_pipeline/test_pipeline_idempotency.py`

- [ ] **RED: Write test**

Submit same `idempotencyKey` twice via HTTP (using TestClient). Second call returns existing record without new journal write.

- [ ] **GREEN: Already implemented in SP4 `commands.py` router** — verify it still works with pipeline. The router checks idempotency BEFORE enqueueing.

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_idempotency.py -v
```

---

## Task 12: Unsupported commands

**Files:**
- Create: `tests/test_pipeline/test_pipeline_unsupported.py`

- [ ] **RED: Write test**

```python
# Submit kind="strategy.pause" — in RUNTIME_COMMAND_KINDS but not implemented
# Expect: command.created journaled, then immediately command.failed with reason UNSUPPORTED_COMMAND
# NOT a 422 — the command is accepted into the journal first
```

- [ ] **GREEN: In `CommandPipeline._process`**

Check `SUPPORTED_SP5_KINDS`. If kind not in set: transition PREPARED→FAILED(UNSUPPORTED_COMMAND), journal, emit event, return.

```python
SUPPORTED_SP5_KINDS = frozenset({
    "position.close", "position.closePartial", "position.modifyProtection",
    "position.closeAll", "order.cancel", "runtime.emergencyKill",
})
```

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_pipeline_unsupported.py -v
```

---

## Task 13: EXECUTION_UNKNOWN is terminal — no retry

**Files:**
- Create: `tests/test_pipeline/test_execution_unknown_no_retry.py`

- [ ] **RED: Write test**

Verify that after a command reaches EXECUTION_UNKNOWN, no re-queue or re-submission happens. The command record stays terminal. PendingIntentRegistry retains the entry.

- [ ] **GREEN: CommandPipeline never re-enqueues terminal states**

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_execution_unknown_no_retry.py -v
```

---

## Task 14: mutationInFlight SLO exclusion

**Files:**
- Create: `tests/test_pipeline/test_mutation_inflight_slo.py`

- [ ] **RED: Write test**

While a command is in SUBMITTING or IN_PROGRESS, its `targetId` is in `_inflight`. The DataFreshnessGate excludes that entity (tick age check skipped for entity under mutation). Cleared on terminal transition.

- [ ] **GREEN: `_inflight` dict managed in CommandPipeline**

Set on ACCEPTED (after gates pass, before dispatch). Clear on COMPLETED/FAILED/TIMED_OUT/EXECUTION_UNKNOWN. Pass to `GateContext.inflight_entities` for gate 3 to skip.

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_mutation_inflight_slo.py -v
```

---

## Task 15: Transition sequence invariant

**Files:**
- Create: `tests/test_pipeline/test_transition_sequence.py`

- [ ] **RED: Write test**

For every command event published, verify `transition.sequence == envelope.sequence`. This is guaranteed by `publish_command_event` building the transition inside `_publish_lock` from `stamped.sequence`.

- [ ] **GREEN: No new code needed** — invariant maintained by EventBus. Test reads journal and verifies.

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_transition_sequence.py -v
```

---

## Task 16: Close exit mapping

**Files:**
- Create: `tests/test_pipeline/test_close_exit_mapping.py`

- [ ] **RED: Write test**

```python
# position.close → exitReason MANUAL
# runtime.emergencyKill → exitReason KILL_SWITCH
```

- [ ] **GREEN: In OutcomeHandler**

Map command kind to exitReason when building close event payload:

```python
EXIT_REASON_MAP = {
    "position.close": "MANUAL",
    "position.closeAll": "MANUAL",
    "runtime.emergencyKill": "KILL_SWITCH",
    "position.closePartial": "PARTIAL_FINAL",
}
```

- [ ] **Run — pass**

```powershell
uv run pytest tests/test_pipeline/test_close_exit_mapping.py -v
```

---

## Task 17: Wire commands router to pipeline

**Files:**
- Modify: `src/metascan/web/routers/commands.py`
- Modify: `src/metascan/web/dependencies.py`

- [ ] **Step 1: Modify `dependencies.py`**

Add:
```python
def get_pipeline(request: Request) -> "CommandPipeline":
    raise NotImplementedError("override in tests or wire via app state")

def get_risk_config(request: Request) -> "RiskConfig":
    raise NotImplementedError("override in tests or wire via app state")
```

- [ ] **Step 2: Modify `commands.py` router**

Change `submit_command` to:
1. Validate `kind` is in `RUNTIME_COMMAND_KINDS` — else 422.
2. Idempotency check (unchanged).
3. Build `RuntimeCommandStatus(state="PREPARED")` (changed from "ACCEPTED").
4. Journal `command.created` event (new — was `command.accepted` in SP4 stub).
5. Enqueue to `CommandPipeline` via `pipeline.enqueue(status)`.
6. Catch `CommandQueueFull` → HTTP 503.
7. Return `{commandId, state: "PREPARED", receivedAt, idempotencyKey}`.

- [ ] **Step 3: Run existing command tests to verify non-regression**

```powershell
uv run pytest tests/test_web/test_api_commands.py -v
```

If SP4 tests assumed `state="ACCEPTED"` in response, update them to expect `state="PREPARED"` (the new initial state).

---

## Task 18: Health mutationInFlight exposure

In `health.py` router or snapshot: expose `mutationInFlight: bool` (true when `pipeline._inflight` is non-empty). This is read-only metadata for the frontend.

- [ ] **Verify `_inflight` is accessible** via pipeline property.

```python
@property
def mutation_in_flight(self) -> bool:
    return len(self._inflight) > 0
```

No separate test file — covered by `test_mutation_inflight_slo.py`.

---

## Final Review & Verification

- [ ] **Run full test suite**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest tests/ -v
```

- [ ] **Verify all 8 gates in order, each with distinct reason code**
- [ ] **Verify SUBMITTING transition: journaled, no SSE event**
- [ ] **Verify EXECUTION_UNKNOWN: terminal, no retry, PendingIntentRegistry retained**
- [ ] **Verify mutationInFlight: `_inflight` dict, asyncio-only, cleared on terminal**
- [ ] **Verify Future timeout: `asyncio.wait_for`; underlying Future not cancelled; late-result → EXECUTION_UNKNOWN**
- [ ] **Verify SIZING_FLOOR_REJECTION: downward floor rejects, never silently rounds**
- [ ] **Verify PendingIntentRegistry: `register_*` on ACCEPTED; asyncio-only; retained on EXECUTION_UNKNOWN**
- [ ] **Verify close exit mapping: MANUAL / KILL_SWITCH**
- [ ] **Verify unsupported commands: accepted→FAILED(UNSUPPORTED_COMMAND), not 422**
- [ ] **Verify unknown kinds: 422, no journal write**
- [ ] **Verify idempotency: same key returns same record**
- [ ] **Verify transition.sequence == event.sequence invariant**
- [ ] **Verify no existing SP1/SP2/SP3/SP4 tests broken**

- [ ] **Write `SP5_SUMMARY.md`**

Summarize decisions, delivered scope, deferred items. Write last, before commit.

- [ ] **Commit**

```bash
git add backend/src/metascan/pipeline backend/src/metascan/mt5/testing/fake_mt5.py backend/src/metascan/mt5/gateway.py backend/src/metascan/config.py backend/src/metascan/web/routers/commands.py backend/src/metascan/web/dependencies.py backend/tests/test_pipeline backend/SP5_PLAN.md backend/SP5_SUMMARY.md
git commit -m "SP5: RiskGate + command execution pipeline"
```
