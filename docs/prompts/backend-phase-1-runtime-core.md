Repo layout: this is a monorepo. The existing frontend lives in src/ (do
NOT modify anything under src/). Build the Python backend in a new
backend/ folder at the repo root. The authoritative contract files are at
src/lib/runtime/HANDOFF.md, src/lib/runtime/runtime-contract.ts,
src/lib/runtime/runtime-types.ts, src/lib/runtime/events/event-schemas.ts,
and src/lib/types.ts — read those instead of frontend-contract/.

You are building the Python backend runtime for XDIRGA METASCAN, a
professional autopilot trading runtime that connects to a REAL MetaTrader 5
account at Exness. The frontend already exists (React, protocol 4.1.0) and
its contract is AUTHORITATIVE. Read these files first and treat them as the
spec you must implement, not suggestions:

- frontend-contract/HANDOFF.md (endpoint table §"/v4", SSE semantics,
  event registry, command registry)
- frontend-contract/runtime-contract.ts (protocolVersion 4.1.0, required
  capabilities, schemaVersion)
- frontend-contract/runtime-types.ts (CockpitSnapshot, Position,
  PositionManagement, ClosedTrade,
  Command lifecycle states)
- frontend-contract/event-schemas.ts (payload shapes per event type)

NON-NEGOTIABLE OPERATING PRINCIPLES (these override any convenience):

1. LIVE ONLY. There is NO demo mode, NO paper-trading mode, NO mock mode in
   the production runtime. The process either connects to the real MT5
   terminal or refuses to serve trading state. Mocks exist ONLY inside the
   test suite (pytest), never behind a runtime flag.
2. BROKER IS THE SOURCE OF TRUTH. Internal state is a cache that is
   continuously reconciled against MT5. On any conflict, MT5 wins and a
   reconciliation event is emitted.
3. SAFETY BEFORE STRATEGY. There is no strategy engine in this phase. The
   runtime must be able to protect itself and its positions before it ever
   generates a trade idea.
4. NO STALE DATA, EVER. Every piece of market/account state carries a
   timestamp. Data older than its freshness budget must never be used for
   a trading decision and must be visibly flagged. Latency is measured,
   exposed, and alarmed — not assumed.
5. CRASH-SAFE BY DESIGN. The laptop can die at any moment. On every boot
   the runtime rebuilds truth from MT5 + its append-only journal and
   resumes managing whatever it finds. Hard SL always lives broker-side so
   positions stay protected even when this process is dead.

=== TARGET ENVIRONMENT ===

- Windows 11, single machine, MetaTrader 5 terminal installed and logged in
  to an Exness account (hedging). Python 3.12.
- Package: `MetaTrader5` official python package (Windows-only, in-process
  IPC to the terminal). It is BLOCKING and NOT thread-safe → all MT5 calls
  must go through ONE dedicated gateway thread with a serialized command
  queue. Nothing else may touch the MT5 API.
- Symbols: configured as base names + broker suffix from config
  (suffix "m" at Exness: XAUUSDm, BTCUSDm, EURUSDm, ...). Never hardcode
  suffixed names in code.
- Stack: FastAPI + uvicorn, pydantic v2, SQLite (WAL mode) for the
  append-only event journal + command store, structlog for structured
  logging. No external DB, no docker, no cloud dependency. Config from
  config.toml + .env (credentials only in .env; never logged, never in any
  API response).

=== ARCHITECTURE (implement exactly this process model) ===

One Python process, three core components:

1. MT5Gateway (dedicated thread)
   - Owns the MetaTrader5 module exclusively. Serialized request queue;
     every call gets a timeout and a measured duration (for SLO metrics).
   - Tight poll loop, target cadence 200–300ms per cycle:
     positions_get / orders_get / account_info + symbol ticks for the
     configured watchlist. Each cycle produces an immutable
     BrokerStateFrame{timestamp, positions, orders, account, ticks} pushed
     to the RuntimeCore. The loop does NOTHING else — no strategy, no
     analytics, no I/O beyond MT5 calls.
   - Boot sequence: initialize() → verify account_info matches configured
     login → verify margin_mode is hedging → for each configured symbol:
     symbol_select + symbol_info, capture digits, point,
     trade_contract_size, volume_min/max/step, trade_stops_level,
     trade_freeze_level, filling modes; fail fast with a precise error if
     any symbol is missing or trading-disabled.

2. RuntimeCore (asyncio, the brain)
   - Consumes BrokerStateFrames, diffs them against internal state, and
     emits domain events (position.opened / position.updated /
     position.closed / account.updated / tick.updated ...) through the
     EventBus with monotonic `sequence`, stable `bootId` (new UUID per
     process start) and `revision` (increments on every state mutation),
     exactly matching the frontend envelope in HANDOFF.md.
   - RECONCILIATION: a position that disappears from MT5 without a
     corresponding bot command is an EXTERNAL CLOSE → look up the closing
     deal in history_deals_get, emit trade.closed with
     exitReason="MANUAL_CLOSE" (full ClosedTrade payload: signed
     commission/swap, netPnl = grossPnl + commission + swap), cancel its
     management plan, journal it. Detection SLO: < 1 second from broker
     fact to emitted event.
   - ALIEN POSITIONS: the operator never opens positions manually. Any
     position whose magic number != the configured bot magic is an anomaly:
     do NOT adopt, do NOT touch; mark runtime degraded
     (reason=ALIEN_POSITION), emit a critical alert event.
   - Journal: append-only SQLite table of every emitted event envelope and
     every command transition. On boot: reconnect MT5, rebuild state from a
     fresh full read (broker wins), compare against last journaled state,
     emit reconciliation events for every difference, then resume.

3. API layer (FastAPI) — implement the /v4 endpoint table from HANDOFF.md:
   - GET /v4/handshake → protocol identity: protocolVersion "4.1.0",
     schemaVersion, schemaHash (see below), runtimeId, bootId, revision,
     granted role. Auth: static bearer token generated at boot, printed
     once to console + written to a local file the UI reads.
   - GET /v4/capabilities → allowed commands + feature flags per the
     contract's capability rules (role, safe-mode, broker-offline gating).
   - GET /v4/snapshot → atomic CockpitSnapshot at (bootId, revision).
     Must be internally consistent — build it from one state view under a
     lock, never from live mutating structures.
   - POST /v4/commands → idempotencyKey semantics: same key returns
     the SAME command record (replay), never a duplicate execution. Command
     lifecycle states and transitions must match
     frontend-contract command-transitions exactly. Commands that reach the
     gateway but yield an ambiguous result (timeout, terminal disconnect
     mid-call) become EXECUTION_UNKNOWN and lock their entity until a
     reconciliation pass proves what happened, then emit
     reconciliation.issue.resolved.
   - GET /v4/commands/{id} → poll one command.
   - GET /v4/events/stream → SSE. `id:` = sequence. Supports Last-Event-ID
     resume from an in-memory ring buffer (>= 10k events); if the client is
     older than the buffer or bootId changed → send system.resync.required
     and expect the client to re-snapshot. Auth via ?token= (EventSource
     cannot set headers). Heartbeat comment every 10s.
   - GET /v4/history/trades → cursor pagination over the journal.
   - GET /v4/health → liveness + the SLO metrics block (below).

SCHEMA HASH: generate pydantic JSON Schema for the full event + command +
snapshot surface, canonicalize (sorted keys, no whitespace), SHA-256. Write
a small CLI (`python -m metascan.contract hash`) that prints it, and a
generated artifact the frontend build can consume. On handshake the
frontend compares hashes → mismatch triggers its SAFE MODE, so the hash
must be stable across process restarts.

=== SAFETY LAYER (active from the very first order; commands in this phase) ===

Even though no strategy exists yet, the runtime accepts operator commands
from the UI (open/close/modify/partial-close, pause/resume autopilot,
kill switch). Every order-producing command passes a RiskGate that
enforces, in order:

1. kill-switch not engaged (kill switch itself must ALWAYS be accepted)
2. runtime not in SAFE MODE / degraded state that blocks trading
3. data freshness: relevant tick age and account age within budget
4. hard SL present in the request or already on the position — an entry
   without a broker-side SL is REJECTED, no exceptions
5. volume within symbol volume_min/max/step; price/SL/TP respect
   trade_stops_level and freeze_level
6. spread guard: current spread <= configured multiple of rolling median
7. exposure guards: max open positions, max volume per symbol, max daily
   realized+unrealized loss (as % of balance at day start, broker
   midnight) → breaching the daily loss limit engages TRADING_HALT until
   manually reset via a privileged command.
   Every rejection emits a command.rejected event with a machine-readable
   reason code. Every gate decision is journaled.

KILL SWITCH: closes nothing by itself in this phase (flatten comes with the
autopilot phase) but immediately blocks all order-producing commands and
sets runtime state HALTED. It must work even when MT5 is disconnected.

=== ANTI-STALE / LATENCY SLOs (expose in /v4/health and as events) ===

Measure continuously, per rolling 1-minute window:

- tick_age_ms per symbol (now - last tick), budget: 1000ms during market
  hours FOR THAT SYMBOL (BTCUSDm trades 24/7 incl. weekends; forex/gold do
  not — session calendars are per-symbol config, never global)
- poll_cycle_ms p50/p95 (budget p95 < 400ms)
- mt5_call_ms p50/p95 per call type
- external_close_detection_ms (measured when they occur)
- command_roundtrip_ms p50/p95 (accepted → broker-confirmed)
  Any budget breach → emit health.slo.breached, set the corresponding
  freshness state that the frontend already renders, and while breached the
  RiskGate rejects order-producing commands with reason=STALE_DATA.

=== PROCESS SURVIVAL (Windows) ===

- Run as a supervised process: provide an NSSM service definition + a
  Task Scheduler XML alternative (auto-start at boot, restart on crash,
  exponential backoff). Document both in README.
- While any bot position is open, prevent system sleep via
  SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED); release when
  flat.
- Graceful shutdown on SIGTERM/CTRL_CLOSE: stop accepting commands, flush
  journal, leave positions protected (broker-side SL), exit. A dirty crash
  must be equivalent in outcome thanks to the boot reconciliation.
- MT5 terminal restart / broker disconnect: gateway detects failed calls,
  sets runtime state DEGRADED_BROKER_OFFLINE (events + health reflect it),
  retries initialize() with backoff, on reconnect performs a full
  reconciliation pass before accepting order-producing commands again.

=== TESTS (pytest; mocks allowed HERE only) ===

- Contract tests: every /v4 endpoint against golden fixtures; SSE resume
  (Last-Event-ID mid-stream, buffer overflow → resync.required, bootId
  change → resync.required); idempotency replay returns identical record.
- Gateway tests with a fake MT5 module: boot verification failures (wrong
  login, netting account, missing symbol), poll diffing (open/update/
  external close), EXECUTION_UNKNOWN on timeout + reconciliation resolve.
- RiskGate: table-driven tests for every gate incl. sign convention
  (netPnl = gross + commission + swap with negative costs) and stale-data
  rejection.
- Crash recovery: kill the core mid-scenario, reboot against the fake
  broker, assert state equals broker truth and reconciliation events fired.

=== DELIVERABLES / DEFINITION OF DONE ===

- `uv`-managed project, `uv run metascan serve` starts the runtime.
- README: setup on Windows, config reference, service install, token
  handoff to the frontend, SLO table.
- All tests green. `python -m metascan.contract hash` stable.
- Demonstrable end-to-end on the real Exness trial server: UI connects
  (handshake → snapshot → SSE), shows live account/positions/ticks; a
  manual close in the MT5 terminal appears in the UI as MANUAL_CLOSE in
  < 1s; kill switch halts trading; pulling the network cable degrades and
  recovers cleanly.

Work in this order, keeping the tree green at each step: project skeleton +
config + contract models + schema hash → journal + EventBus → fake-MT5
gateway + tests → API endpoints + SSE → RiskGate + command pipeline →
real MT5Gateway wiring → boot reconciliation + survival features → README.
Ask me before deviating from the frontend contract in ANY way; the contract
wins over your preferences.
