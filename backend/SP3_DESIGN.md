# SP3 — Fake-MT5 Gateway + Broker State Diff Design

Status: locked requirements for implementation. No frontend contract deviation.
SP1 contract models and SP2 EventBus/journal are inputs; this slice owns broker
poll ownership, immutable frames, async diffing, and test doubles only.

Out of scope: order execution, RiskGate, FastAPI/SSE, snapshot rebuild, SP7
history deal enrichment as a full subsystem, command pipeline, real-terminal
wiring beyond the production adapter path.

## 1. Goal

Deliver a production MT5 gateway and async consumer that:

- injects the MT5 module through **one seam** (tests inject a fake; production
  injects the official `MetaTrader5` package)
- runs all exact MT5 API calls exclusively on a **dedicated gateway thread**
- hands off **immutable full frames** to asyncio via
  `loop.call_soon_threadsafe`
- coalesces frames with **bounded latest-frame** handoff (drop older unconsumed
  frames; count drops; overrun → DEGRADED)
- diffs frames against last processed state and emits **canonical SP1 event
  types** through the SP2 EventBus without contract deviations
- classifies broker-side position changes using an injected
  `PendingIntentLookup` (default false) so tests can flip classification
- measures staleness/latency with **monotonic clocks only** for ages/durations/
  percentiles; wall clock only for event timestamps
- never executes orders

Accepted product trade-off: **transient-position blind spot** between poll
cycles is accepted; **SP7 history backstop** will reconcile missed full closes
later. SP3 must not invent deal history as a hard dependency for live open-set
diffing.

## 2. Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│ asyncio Runtime (consumer task)                                  │
│  BrokerStateConsumer                                             │
│   - waits on frame queue (coalesced latest)                      │
│   - diffs last_processed vs frame                                │
│   - PendingIntentLookup (sync, cheap, in-memory)                 │
│   - EventBus.publish(...)  [SP2: journal then fan-out]           │
│   - connection/staleness state machine                           │
└────────────────────────────▲─────────────────────────────────────┘
                             │ call_soon_threadsafe → put latest frame
                             │ (bounded slot; coalesce drop count++)
┌────────────────────────────┴─────────────────────────────────────┐
│ dedicated gateway thread (ONLY MT5 call owner)                   │
│  Mt5Gateway                                                      │
│   - owns injected mt5 module exclusively                         │
│   - boot: initialize → account verify → symbol resolve/select    │
│   - poll loop default 250ms: positions_get, account_info, ticks  │
│   - builds immutable BrokerStateFrame                            │
│   - records cycle timing (monotonic)                             │
└────────────────────────────▲─────────────────────────────────────┘
                             │ only this thread
┌────────────────────────────┴─────────────────────────────────────┐
│ injected MT5 module seam                                         │
│  production: MetaTrader5                                         │
│  tests: FakeMt5 (scriptable surface)                             │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 One seam rule

| Rule | Behavior |
|---|---|
| Single injection point | `Mt5Gateway(mt5_module=..., ...)` — no alternate import paths that call MT5 |
| Production construction | factory/wiring imports `MetaTrader5` once and injects it |
| Tests | inject `FakeMt5`; never import real `MetaTrader5` in unit tests |
| Call site exclusivity | every `mt5.*` invocation that touches terminal IPC runs on the gateway thread |
| No MT5 from asyncio | consumer, EventBus, journal workers must not call the module |

### 2.2 Threading model

| Component | Thread | Responsibilities |
|---|---|---|
| `Mt5Gateway` poll + boot | dedicated `threading.Thread` | all MT5 calls; frame build; handoff schedule |
| Async consumer | asyncio event loop | queue get, diff, EventBus publish, state transitions |
| EventBus journal writer | SP2 single journal executor thread | SQLite only (unchanged) |
| FakeMt5 | called only from gateway thread in production path tests | scriptable broker world |

Handoff from gateway → loop:

```text
loop.call_soon_threadsafe(self._slot.offer, frame)
```

`_slot.offer` runs on the event loop thread and implements latest-frame
coalescing (see §4). Gateway never awaits asyncio futures for poll cadence.

## 3. Components and files

```text
backend/src/metascan/mt5/
  __init__.py              # re-exports public types
  types.py                 # BrokerStateFrame, PositionRow, AccountRow, TickRow,
                           # SymbolMeta, ConnectionHealth, GatewayMetrics
  symbols.py               # base+suffix resolver; no hardcoded symbol names
  pending_intent.py        # PendingIntentLookup protocol + NullPendingIntentLookup
  gateway.py               # Mt5Gateway: boot, poll loop, thread ownership, handoff
  consumer.py              # BrokerStateConsumer: diff + EventBus publish + state
  clocks.py                # MonotonicClock protocol; WallClock for event ISO only
  metrics.py               # bounded sample windows; p50/p95; overrun counters

backend/src/metascan/mt5/testing/
  __init__.py
  fake_mt5.py              # FakeMt5 exact listed surface

backend/tests/
  test_mt5_gateway_thread.py
  test_mt5_frame_handoff.py
  test_mt5_boot_verify.py
  test_mt5_diff_positions.py
  test_mt5_external_close.py
  test_mt5_external_partial.py
  test_mt5_external_modify.py
  test_mt5_foreign_magic.py
  test_mt5_connection_state.py
  test_mt5_metrics_clocks.py
  test_mt5_symbols.py
  test_mt5_fake_scriptable.py
  test_mt5_asyncio_nonblocking.py
  test_mt5_none_errors.py
```

No changes under `src/` (frontend). No SP1 field renames. No SP2 journal/bus
API changes required beyond **calling** `EventBus.publish`.

## 4. Immutable frames and handoff

### 4.1 BrokerStateFrame

Frozen/immutable snapshot of one poll cycle. Built entirely on the gateway
thread; never mutated after construction.

```text
BrokerStateFrame (frozen)
  frame_id: int                    # gateway-monotonic, starts at 1
  cycle_started_m: float           # monotonic
  cycle_finished_m: float          # monotonic
  cycle_duration_ms: float         # derived from monotonic
  polled_at_wall: str              # ISO-8601 UTC wall for informational stamps only
  positions: tuple[PositionRow, ...]
  account: AccountRow | None       # None if account_info failed/returned None
  ticks: frozendict[str, TickRow]  # key = resolved broker symbol
  symbol_meta: frozendict[str, SymbolMeta]  # captured at boot; copied into frames
  errors: tuple[GatewayError, ...] # per-call failures this cycle (non-fatal)
  mt5_last_error: tuple[int, str] | None
```

`PositionRow` fields (broker-native, not yet UI `Position`):

```text
ticket: int
symbol: str              # broker symbol (suffixed)
magic: int
volume: float
price_open: float
price_current: float
sl: float                # 0.0 means unset (MT5 convention) → map to None at domain edge
tp: float
profit: float
swap: float
commission: float        # 0 if unavailable on position struct
type: int                # MT5 position type (buy/sell)
time_msc: int            # open time ms if available else 0
identifier: int          # position identifier when present
comment: str
```

`AccountRow`: login, balance, equity, margin, free_margin, margin_level,
currency, trade_mode / margin_mode fields needed for boot verify and account
update events.

`TickRow`: symbol, bid, ask, last, time_msc, volume (as available).

### 4.2 Latest-frame coalescing slot

Single-slot handoff on the event loop:

| Condition | Behavior |
|---|---|
| Slot empty | store frame; if consumer waiting, wake it |
| Slot occupied (unconsumed) | **replace** with newer frame; `handoff_dropped_count += 1`; `handoff_overrun = True` |
| Consumer takes frame | clear slot; process that frame only |

Properties:

- Bound = 1 outstanding unconsumed frame (latest wins).
- Dropped frames are never queued for later delivery.
- `handoff_dropped_count` is monotonic process counter (exposed on metrics).
- While `handoff_overrun` is true for a cycle of observation, connection health
  may enter **DEGRADED** (see §9) with reason `HANDOFF_OVERRUN`.
- Consumer processes **full** frames only; no partial field streams.

### 4.3 Accepted blind spot

If a position opens and fully closes between two successful polls, SP3 open-set
diff never sees it. Product accepts this transient blind spot. SP7 history
backstop will recover closed trades from deal history. SP3 must not block on
`history_deals_get` for the live poll path.

When a position **is** observed then disappears, SP3 emits external close
events immediately (no history dependency for classification as external vs
pending-intent). Optional best-effort deal lookup for PnL enrichment is **not**
required in SP3; payload fields use last-known position row + zeros/None where
unknown, remaining contract-valid.

## 5. Poll loop (gateway thread)

### 5.1 Cadence

| Setting | Default | Source |
|---|---|---|
| `poll_interval_ms` | **250** | config override allowed; clamp sensible range e.g. 50–2000 |
| Target cycle content | positions + account + watchlist ticks | every cycle |
| orders_get | **not required** in SP3 | deferred; frames may carry empty orders |

Cycle algorithm (exact):

1. `t0 = monotonic()`
2. `positions = mt5.positions_get()` — tolerate `None` → treat as empty **only if**
   last_error indicates “no positions”; otherwise record error, keep previous
   positions **unavailable** flag for this cycle (see §10)
3. `account = mt5.account_info()` — `None` → error, `account=None` on frame
4. For each resolved watchlist symbol: `mt5.symbol_info_tick(symbol)`
5. `t1 = monotonic()`; build immutable frame
6. `call_soon_threadsafe(slot.offer, frame)`
7. Sleep remainder so cycle targets `poll_interval_ms` from `t0` (if cycle
   overran interval, sleep 0 and count `cycle_overrun`)

### 5.2 Boot sequence (fail-fast)

On gateway start, still on the gateway thread, before first poll:

1. `mt5.initialize(...)` — credentials from config/env; never log password
2. `account_info()` — must match configured login when login configured;
   fail-fast with precise error if mismatch
3. Verify hedging / expected margin mode if contract requires hedging account;
   fail-fast on netting when product requires hedge
4. For each configured **base** symbol in watchlist:
   - resolve broker name via suffix (§8)
   - `symbol_select(resolved, True)`
   - `symbol_info(resolved)` — fail-fast if missing, not visible, or
     trading-disabled
   - capture `SymbolMeta`: digits, point, trade_contract_size, volume_min/max/step,
     trade_stops_level, trade_freeze_level, filling modes, base, resolved
5. Publish/mark boot success to consumer; enter poll loop

Boot failure: gateway does not enter “healthy poll”; reports DISCONNECTED or
ERROR path; asyncio consumer emits connection transition events; process does
not pretend CONNECTED.

### 5.3 Exact MT5 surface used by production path

Only these call names are allowed through the seam in SP3 (tests assert no
others from gateway code):

| Call | When |
|---|---|
| `initialize` | boot / reconnect |
| `shutdown` | graceful stop |
| `account_info` | boot + every poll |
| `positions_get` | every poll |
| `symbol_select` | boot (and reconnect re-verify) |
| `symbol_info` | boot metadata |
| `symbol_info_tick` | every poll per watchlist symbol |
| `last_error` | after None/failure returns |
| `terminal_info` | optional boot/health; if used, on gateway thread only |

**Forbidden in SP3:** `order_send`, `order_check`, `orders_get` (optional later),
history APIs as poll dependencies, any copy-trade helpers.

## 6. PendingIntentLookup

### 6.1 Protocol (exact)

Injected, **synchronous**, **cheap**, **in-memory**. Called only from the async
consumer during diff classification. Default implementation returns false for
all queries.

```python
class PendingIntentLookup(Protocol):
    def has_pending_close(self, ticket: int) -> bool: ...
    def has_pending_partial(self, ticket: int, volume: float) -> bool: ...
    def has_pending_modify(self, ticket: int) -> bool: ...
```

```python
class NullPendingIntentLookup:
    def has_pending_close(self, ticket: int) -> bool:
        return False
    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False
    def has_pending_modify(self, ticket: int) -> bool:
        return False
```

### 6.2 Classification rules

For each observed change against `last_processed` positions keyed by ticket:

| Observation | Pending intent | Classification | Events (canonical types) |
|---|---|---|---|
| Ticket missing (was present) | `has_pending_close(ticket)` true | bot-initiated close (intent acknowledged path) | SP3 emits **no** “external” close set; may emit nothing domain-wise beyond optional internal note — **command pipeline (later) owns bot close completion**. For SP3 isolation tests, when pending close true: do **not** emit external `trade.closed` with MANUAL |
| Ticket missing | `has_pending_close` false | **external full close** | `position.closed` + `trade.closed` with `exitReason="MANUAL"` (SP1; never `MANUAL_CLOSE`) |
| Volume decreased, ticket remains | `has_pending_partial(ticket, new_volume)` true | bot partial | no external partial event from SP3 |
| Volume decreased | pending partial false | **external partial close** | `position.partially_closed` (exact frontend type) + `position.updated` as needed |
| SL and/or TP changed | `has_pending_modify(ticket)` true | bot modify | no external modification event |
| SL and/or TP changed | pending modify false | **external modification** | `position.protection_changed` (exact protection event) and/or `position.updated` |
| Other field changes (price, profit, swap…) | n/a | mark-to-market | `position.updated` when material |
| New ticket, magic == bot_magic | n/a | bot/adopted managed open | `position.opened` |
| New ticket, magic != bot_magic | n/a | **foreign / quarantine** | never adopt/manage; see §7 |

`volume` argument to `has_pending_partial` is the **observed new volume** after
shrink (exact signature required so tests can key intents tightly).

Test classification flips: unit tests inject a lookup that returns true/false
per ticket to force external vs non-external paths without a command stack.

## 7. Foreign magic (QUARANTINE)

Configured `bot_magic` from `config.toml` (`runtime.bot_magic`).

| Rule | Behavior |
|---|---|
| Detect | any position with `magic != bot_magic` in a frame |
| Adopt | **never** — do not create managed domain ownership, plans, or strategy binding |
| Manage | **never** — no modify/close automation against it in this slice |
| Runtime health | enter **DEGRADED** with reason `ALIEN_POSITION` / quarantine |
| Alarm | emit `alert.created` severity **CRITICAL** (canonical type) with payload identifying ticket, symbol, magic, expected magic |
| Optional | `reconciliation.issue.detected` if issue tracking is cheap; not required to block SP3 if alert + degraded are present |
| Persistence of flag | quarantine remains while any foreign position is open; clear when none remain **and** no other degrade reasons |

Foreign positions may still appear in raw frame metrics for observability but
must not enter the managed position map used for bot lifecycle.

## 8. Symbol resolver

| Rule | Behavior |
|---|---|
| Config | base names only in `runtime.symbols.watchlist` (e.g. `XAUUSD`) |
| Suffix | `runtime.symbol_suffix` (e.g. `"m"` → `XAUUSDm`) |
| Resolve | `resolved = base + suffix` (suffix may be empty string) |
| Hardcoding | **no** suffixed literals in production code or tests of production modules |
| Fail-fast | missing `symbol_info` / not selected / trade mode disabled → boot error naming the **base and resolved** names |
| Frame keys | ticks and meta keyed by resolved broker symbol; domain events may expose the symbol string the broker uses (resolved), consistent with UI expectations |

## 9. Connection and staleness state

### 9.1 States (broker connection projection)

Use contract `ConnectionState` values relevant to broker path:

| State | Meaning |
|---|---|
| `CONNECTED` | recent successful poll cycle; ages within budget |
| `DEGRADED` | connected enough to poll but SLO/overrun/alien/partial errors |
| `DISCONNECTED` | initialize failed, repeated hard failures, or shutdown |

Transitions emit canonical events:

- `broker.connection.changed` — payload includes `state`, previous state, reason codes
- `runtime.health.changed` — subsystem key e.g. `mt5-gateway` / `broker`
- `runtime.connection.changed` when runtime-level connection projection changes
- `runtime.state.changed` only when SP3 is wired as the authority for that field
  in this slice’s consumer (if RuntimeCore not yet present, consumer may still
  emit broker/health events; must not invent non-catalog types)

### 9.2 Transition triggers

| From → To | Triggers |
|---|---|
| → CONNECTED | successful boot + successful poll; ages ok; no active quarantine/overrun degrade |
| → DEGRADED | handoff overrun; cycle p95 budget breach; tick age budget breach; alien position; repeated soft call errors with some data |
| → DISCONNECTED | initialize failure; consecutive hard poll failures beyond threshold; explicit shutdown; terminal gone |

Budgets (defaults aligned with config):

| Metric | Budget | Source |
|---|---|---|
| tick age (in-session) | 1000ms | `safety.tick_age_budget_ms` |
| poll cycle p95 | 400ms | `safety.poll_cycle_p95_budget_ms` |

Session calendars per symbol are **not** fully implemented in SP3 if absent;
when session calendar not available, apply tick budget only when ticks were
previously advancing, and do not false-alarm forever-frozen off-session symbols
if config marks them session-limited — minimum viable: crypto-like symbols in
watchlist treated 24/7; others use last-advance heuristic (degrade when
previously live ticks stop within budget during detected active period). Document
heuristic in code comments only if needed; no new event types.

### 9.3 Clocks

| Use | Clock |
|---|---|
| ages, durations, cycle time, percentiles, budgets | **monotonic exclusively** |
| `occurredAt` / `emittedAt` / informational `polled_at_wall` | **wall clock ISO-8601 UTC** only |

Never compute age as wall_now - wall_then for SLO decisions.

### 9.4 Metrics (bounded samples)

`GatewayMetrics` maintains ring buffers (fixed capacity, e.g. 256 samples) of:

- `poll_cycle_ms`
- per-call `mt5_call_ms` (positions_get, account_info, symbol_info_tick aggregate or per type)
- handoff drop increments
- cycle overrun flags
- handoff overrun flags

Expose:

- p50 / p95 for cycle and call timings
- counters: `cycle_overruns`, `handoff_overruns`, `handoff_dropped_count`
- last frame monotonic age as observed by consumer

Percentiles from bounded windows only (no unbounded lists).

## 10. Diff consumer (asyncio)

### 10.1 last_processed

Consumer keeps:

```text
last_positions: dict[int, PositionRow]   # ticket → row (managed + observed bot magic)
last_account: AccountRow | None
last_ticks: dict[str, TickRow]
last_frame_id: int
connection_state: ConnectionState
quarantine_tickets: set[int]
```

On each dequeued frame:

1. Update metrics ages (monotonic)
2. Recompute connection state; emit transition events if changed
3. Diff positions (bot magic only for managed map; scan all for foreign)
4. Diff account → emit account-facing update if material (use existing catalog
   events only; if no dedicated `account.updated` type exists in SP1 catalog,
   fold account fields into health/broker payloads already allowed — **do not
   invent types**. SP1 catalog has no `account.updated` / `tick.updated`;
   therefore SP3 does **not** emit non-catalog tick/account event types.
   Account/tick data remain on frames for later snapshot builders.
5. Publish domain position/trade/alert events via EventBus

### 10.2 External full close payload rules

When external full close:

1. Emit `position.closed` with `positionId` = stable id derived from ticket
   (string form of ticket or `pos:{ticket}` — pick one scheme and use
   everywhere: **`str(ticket)`** for broker-ticket-aligned ids in SP3)
2. Emit `trade.closed` with ClosedTrade-shaped payload:
   - `exitReason`: **`MANUAL`** (SP1 `map_exit_reason` / TradeExitReason)
   - sign convention: `netPnl == grossPnl + commission + swap`
   - unknown costs → `0.0` with honesty in tags if needed (`["sp3-no-history"]`)
   - `strategyId`: configured placeholder or `"unknown"` consistent with models
   - never use `MANUAL_CLOSE` literal

`mutates_state=True` for these publishes.

### 10.3 External partial

Emit `position.partially_closed` with payload including `positionId`, previous
volume, new volume, closed volume delta; update last_positions volume.
Also emit `position.updated` if the UI relies on full row refresh.

### 10.4 External SL/TP modification

Emit `position.protection_changed` when protection fields change externally;
include prior/new SL/TP. Emit `position.updated` when broader row material
changes. Classification gated by `has_pending_modify`.

### 10.5 Open

New bot-magic ticket → `position.opened` with mapped fields best-effort from
`PositionRow` → contract `Position` shape (management null in SP3).

## 11. EventBus integration (SP2)

| Rule | Behavior |
|---|---|
| Publish path | only `await bus.publish(envelope_partial, mutates_state=...)` |
| Envelope | SP1 `RuntimeEventEnvelope` fields; bus stamps `bootId`/`sequence`/`revision` |
| Types | only `RUNTIME_EVENT_TYPES` catalog strings |
| Source | `LOCAL_RUNTIME` |
| Ordering | consumers rely on sequence; timestamps informational |
| Failure | publish errors propagate to consumer task; gateway keeps polling; consumer may restart policy later — SP3 logs CRITICAL and sets DEGRADED on repeated publish failure |
| No dual bus | no side channel of domain events |

## 12. Lifecycle

1. **Construct:** inject mt5 module, bus, config, PendingIntentLookup, clocks, loop ref
2. **Start:** create frame slot; start gateway thread; boot on thread; start
   asyncio consumer task
3. **Run:** poll → handoff → diff → publish
4. **Stop (graceful):**
   - signal gateway stop event
   - join gateway thread with timeout; call `mt5.shutdown()` on gateway thread
   - consumer drains optional last frame; then exits
   - do not delete journal rows
5. **Crash:** next process boot is SP2 new bootId + later full reconciliation
   (out of SP3)

Reconnect (minimal SP3): on hard disconnect, gateway thread retries
`initialize` with backoff on the **same** thread; emits DISCONNECTED then
CONNECTED/DEGRADED; full SP2 journal rebuild not required beyond events.

## 13. Error handling and severity

| Failure | Severity | Behavior |
|---|---|---|
| `positions_get` returns None + error | WARNING/ERROR by persistence | frame.errors append; if consecutive hard fails → DISCONNECTED |
| `account_info` None | ERROR | account=None; DEGRADED/DISCONNECTED by streak |
| single tick None | WARNING | omit/miss that symbol tick; others proceed |
| boot symbol missing | CRITICAL | fail boot; DISCONNECTED |
| wrong login | CRITICAL | fail boot |
| alien magic | CRITICAL alert | QUARANTINE/DEGRADED |
| handoff overrun | WARNING | DEGRADED while overrun condition holds |
| cycle overrun vs interval | INFO/WARNING | counter++; p95 may trip budget |
| EventBus closed mid-run | ERROR | consumer stops cleanly |
| unexpected exception in poll | ERROR | log; count failure; continue or disconnect by threshold |
| unexpected exception in diff | ERROR | log; skip frame; do not crash process |

Resilience principle: **None/errors never crash the poll thread by default**;
structured errors on the frame; severity drives state and alerts.

## 14. FakeMt5 (tests only)

Exact scriptable surface matching production allowed calls:

```text
FakeMt5
  initialize(**kwargs) -> bool
  shutdown() -> None
  account_info() -> SimpleNamespace | None
  positions_get(*args, **kwargs) -> tuple[SimpleNamespace, ...] | None
  symbol_select(symbol, enable) -> bool
  symbol_info(symbol) -> SimpleNamespace | None
  symbol_info_tick(symbol) -> SimpleNamespace | None
  last_error() -> tuple[int, str]
  terminal_info() -> SimpleNamespace | None   # if production uses it
```

Scriptable behaviors (required for tests):

| Capability | API idea |
|---|---|
| Appear / disappear positions | `set_positions([...])` / `remove_position(ticket)` |
| Shrink volume | `set_volume(ticket, volume)` |
| Change SL/TP | `set_protection(ticket, sl, tp)` |
| Ticks freeze / advance | `freeze_ticks()` / `advance_ticks(delta_msc)` / `set_tick(symbol, bid, ask, time_msc)` |
| Failures | `fail_next(call_name, times=1)` / `set_return(call_name, None)` |
| Sleep / block | `block_call(call_name, seconds)` to prove asyncio non-blocking |
| last_error codes | `set_last_error(code, msg)` |
| Account | `set_account(...)` |
| Magic | positions carry magic field for foreign tests |
| Thread affinity helper | record `threading.get_ident()` per call for “all MT5 same thread” asserts |

Fake lives under `metascan.mt5.testing` only. Production packaging must not
require it at runtime.

## 15. Testing plan (required)

| Case | Assert |
|---|---|
| All MT5 calls same thread | Fake records one thread id for all calls during run |
| Asyncio non-blocking | gateway `block_call("positions_get", 0.3)` while asyncio task progresses / consumer wait uses timeouts; loop not frozen |
| Boot wrong login | fail-fast; not CONNECTED |
| Boot missing symbol | fail-fast naming base+resolved |
| Boot hedging mismatch | fail-fast when required |
| Poll positions open | `position.opened` for bot magic |
| Position update MTM | `position.updated` |
| External full close | missing ticket + pending close false → `position.closed` + `trade.closed` `exitReason=="MANUAL"` |
| Pending close true | missing ticket → **no** external MANUAL trade.closed |
| External partial | volume shrink + pending partial false → `position.partially_closed` |
| Pending partial true | shrink → no external partial event |
| External SL/TP | change + pending modify false → `position.protection_changed` |
| Pending modify true | SL/TP change → no external protection event |
| Foreign magic | DEGRADED/quarantine + `alert.created` CRITICAL; no manage/adopt |
| Handoff coalesce | produce frames faster than consumer; dropped count ≥ 1; only latest processed continuity |
| Handoff overrun degraded | DEGRADED with overrun reason while condition active |
| Cycle metrics | p50/p95 finite; bounded sample size; overruns counted |
| Monotonic ages | monkeypatch wall ≠ monotonic; budgets use monotonic |
| None resilience | positions_get None with error → no crash; state degrades appropriately |
| Symbol resolver | base+suffix; no hardcoded `XAUUSDm` in gateway modules (grep test optional) |
| No order execution | gateway source has no order_send |
| EventBus integration | published envelopes journaled (SP2) with monotonic sequence |
| Classification flips | same frame sequence, different PendingIntentLookup → different event sets |

## 16. Decision notes

1. **One injected MT5 seam** — single ownership boundary; tests never need
   network or terminal.
2. **Dedicated gateway thread exclusively owns MT5 calls** — official package
   is blocking and not thread-safe.
3. **Immutable full frames** — diff is pure function of last_processed + frame.
4. **Latest-frame coalescing (bound 1)** — prefer freshness over backlog under
   load; count drops; overrun degrades.
5. **call_soon_threadsafe** — only legal cross-thread schedule into asyncio.
6. **PendingIntentLookup default false** — without command stack, all broker
   changes classify external; tests flip truths.
7. **exitReason MANUAL** — SP1 authority; no `MANUAL_CLOSE`.
8. **External partial event type `position.partially_closed`** — catalog exact.
9. **External SL/TP → `position.protection_changed`** (+ `position.updated` as
   needed) — catalog exact; not a new type.
10. **Foreign magic → quarantine/degraded + CRITICAL alert; never adopt**.
11. **Transient blind spot accepted; SP7 history backstop** — SP3 does not
    block poll on history.
12. **No account.updated / tick.updated** — not in SP1 catalog; frames carry
    data for later snapshot/API slices.
13. **No order execution in SP3**.
14. **Poll default 250ms** — within phase-1 200–300ms band.
15. **Monotonic for SLO math; wall for event stamps only**.
16. **Null/error resilient poll** — severity + state, not process death.
17. **SP2 EventBus only** — commit-before-fanout preserved; no contract drift.

## 17. Out of scope (explicit)

- `order_send` / command execution / RiskGate
- FastAPI, SSE, handshake token
- Full boot journal vs broker rebuild (later RuntimeCore)
- SP7 deal history enrichment and missed-trade backfill
- Strategy, management plans automation
- orders_get stream and pending order domain events
- Multi-account

## 18. Self-review checklist

- No `TBD` / `TODO` / placeholder APIs in this document.
- PendingIntentLookup method names exact:
  `has_pending_close(ticket)`, `has_pending_partial(ticket, volume)`,
  `has_pending_modify(ticket)`.
- External close uses `trade.closed` + `exitReason="MANUAL"` only.
- External partial uses `position.partially_closed`.
- External SL/TP uses `position.protection_changed`.
- Foreign magic never adopted; quarantine + alert + degraded.
- Handoff: immutable frames, latest-only coalesce, drop count, overrun degrade.
- All MT5 calls on gateway thread; asyncio consumer non-blocking.
- Clocks split monotonic vs wall documented.
- FakeMt5 surface lists scriptable appear/disappear/shrink/ticks/fail/None/sleep.
- SP2 EventBus integration without new event type strings outside catalog.
- Blind spot + SP7 backstop recorded as accepted decision.
- File map and test matrix complete for implementation planning.

(End of file)
)
