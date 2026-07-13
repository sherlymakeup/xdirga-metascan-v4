# SP5: Authoritative Command Pipeline Specification

**Status:** Implementation authority

This document supersedes every prior SP5 plan, design, summary, and ruling. It is the sole backend SP5 authority, alongside the frontend runtime contract. Conflicting prior behavior is invalid.

## 1. Scope

SP5 implements one command pipeline for transport and internal ingress, MT5 command execution, command journaling, safety controls, reconciliation-safe uncertainty handling, and canonical frontend events. It does not implement strategy automation, multi-account operation, or deal-history reconciliation policy beyond the verification reads defined here.

## 2. Ingress, identity, idempotency

Every command has an internal-only `origin`: `TRANSPORT` or `INTERNAL`. It is persisted and available to runtime policy, never serialized in an MT5 request or public transport payload. Internal DB entry commands persist `execution_kind` as the uppercase namespace value `INTERNAL_ENTRY_MARKET`; `origin` is `INTERNAL`. No REST transport payload, public event, MT5 request, or `RuntimeCommandStatus` value exposes `execution_kind`.

Both origins enter the same pipeline and use identical lifecycle, journal, locking, safety classification, and outcome handling. Transport accepts only registered control/reduce command kinds. REST is transport-only: query commands persist `origin=TRANSPORT`; unknown command IDs return HTTP 404 without creating an internal command. Internal ingress may also submit registered entry commands. Command events pass through the command payload `kind` unchanged; they do not derive, translate, or expose `execution_kind`. Unknown kinds fail request validation with HTTP 422 before persistence. Authentication is not an SP5 gate.

`RuntimeCommandStatus` is a pure transport enum. It represents only transport-facing command status and contains no internal execution identity, origin, or `execution_kind` members.

Phase 2 contract: REST remains transport/query only; internal entry identity is represented exclusively by persisted `origin=INTERNAL` and `execution_kind=INTERNAL_ENTRY_MARKET`; event payloads retain their command `kind` passthrough; absent internal command IDs are REST 404s.

`InternalEntryRequest` has exactly these request fields: `symbol`, `side` (`BUY` or `SELL`), optional `stopLoss`, optional `takeProfit`, and optional `riskFraction`. `volume` is structurally absent. A supplied `price` may be accepted by the input model solely so validation deterministically rejects it with `PENDING_ENTRIES_NOT_SUPPORTED`; no pending-entry behavior exists. Entry execution uses the current market tick obtained on the gateway thread. Gate 2 validates side-consistent SL/TP values before entry sizing or broker I/O. Entry request comments must include `CALIBRATE-SP6`.

`request_json` is the canonical, sorted-key, compact UTF-8 JSON representation of the validated command request, excluding internal-only fields. The idempotency key uniquely identifies a command request:

- Same key plus byte-identical `request_json`: replay the existing command response; write no command, event, transition, or broker request.
- Same key plus different `request_json`: return conflict; write no command, event, transition, or broker request.
- New key: atomically create the command row, `command.created` event, and `PREPARED` transition in one journal bundle before queueing.

## 3. Lifecycle, events, reasons

Lifecycle is:

```text
PREPARED → SUBMITTING → ACCEPTED → IN_PROGRESS → COMPLETED
                         ├────────→ FAILED
                         ├────────→ TIMED_OUT → EXECUTION_UNKNOWN
                         └────────→ EXECUTION_UNKNOWN
PREPARED → FAILED | CANCELLED
```

`SUBMITTING` is journaled but emits no SSE envelope. Every other transition emits exactly one canonical command event through the existing journal-backed event path; its transition sequence equals the event envelope sequence. Terminal states are `COMPLETED`, `FAILED`, `TIMED_OUT`, `EXECUTION_UNKNOWN`, and `CANCELLED`. No terminal command is resent automatically.

Canonical reasons are exactly:

| Outcome | Reasons |
|---|---|
| `FAILED` | `IDEMPOTENCY_CONFLICT`, `VALIDATION_FAILED`, `PENDING_ENTRIES_NOT_SUPPORTED`, `SAFETY_CLASSIFICATION_FAILED`, `MUTATION_SCOPE_LOCKED`, `ENTRY_NOT_ELIGIBLE`, `ENTRY_EXPOSURE_LIMIT`, `MISSING_HARD_SL`, `SIZING_FLOOR_REJECTION`, `INVALID_VOLUME`, `BROKER_REJECTED`, `ORDER_CHECK_REJECTED`, `UNSUPPORTED_COMMAND`, `QUEUE_FULL` (`INVALID_VOLUME` is the canonical failure for missing, zero, negative, or non-finite sizing metadata) |
| `TIMED_OUT` | `GATEWAY_TIMEOUT` |
| `EXECUTION_UNKNOWN` | `OUTCOME_AMBIGUOUS`, `BROKER_DISCONNECT_MID_CALL` |
| `CANCELLED` | `OPERATOR_CANCEL` |

The only emitted SP5 event types are existing frontend-catalog types: `command.created`, `command.accepted`, `command.progress`, `command.completed`, `command.failed`, `command.timed_out`, `command.execution_unknown`, `reconciliation.issue.detected`, `reconciliation.issue.resolved`, `safety.kill.started`, `safety.kill.progress`, `safety.kill.completed`, and `safety.kill.failed`. Command creation and rejection metadata include origin, request fingerprint, classification, gate, canonical reason, target scope, and correlation identifiers without leaking transport secrets.

## 4. Exact RiskGate order

The pipeline runs exactly these eight gates, in this order. First failure short-circuits. No old gate names or additional numbered gates exist.

1. **idempotency** — Apply the atomic replay/conflict/new-request rules in section 2.
2. **validation** — Validate registered kind, schema, required target, numeric finiteness, symbol/ticket ownership, command-specific fields, and side-valid entry SL/TP. An entry `price`, if model-accepted, rejects deterministically with `PENDING_ENTRIES_NOT_SUPPORTED`; all other invalid input rejects `VALIDATION_FAILED`.
3. **safety classification** — Classify command as `ENTRY`, `REDUCE`, `PROTECTION`, `CANCEL`, `CONTROL`, or `EMERGENCY`; classify whether broker mutation may increase exposure. Reject impossible or unsafe classifications with `SAFETY_CLASSIFICATION_FAILED`.
4. **mutation scope lock** — Lock each affected bot-magic position, pending order, symbol entry scope, or runtime control scope before broker I/O. Conflicting overlapping mutations reject `MUTATION_SCOPE_LOCKED`. Locks survive ambiguity and release only after a determinate outcome or verified reconciliation.
5. **entry-only eligibility** — For `ENTRY` only, require entries enabled, runtime ready, safety mode clear, fresh required runtime facts, acceptable market conditions, and no active halt. Reduce, protection, cancel, control, and emergency commands do not fail this gate. Reject `ENTRY_NOT_ELIGIBLE`.
6. **entry-only exposure** — For `ENTRY` only, enforce configured maximum position count, symbol volume, aggregate exposure, daily-loss halt, and `riskFraction <= maxRiskFraction`. Reject `ENTRY_EXPOSURE_LIMIT`; a risk fraction above the maximum rejects without clamping. Persist the halt transition before subsequent entry decisions.
7. **entry-only hard-SL+risk sizing downward floor** — For `ENTRY` only, require a broker-side hard stop loss, calculate risk-based volume from current facts, normalize only downward to the symbol volume step, then reject if normalized volume is below `volume_min`, zero, non-finite, or differs from a required fixed requested volume. Never round upward, silently enlarge risk, or create dust. Reasons are `MISSING_HARD_SL`, `SIZING_FLOOR_REJECTION`, or `INVALID_VOLUME`.

   Sizing is exact Decimal arithmetic. Convert every numeric value at every boundary with `Decimal(str(value))`; no sizing expression, comparison, fixture, or property test may mix `float` and `Decimal`. Assert every required sizing input is positive before calculation. Let `R = equity * riskFraction`, `D = abs(entryPrice - stopLoss)`, `L = (D / tick_size) * tick_value_loss`, `V_raw = R / L`, and `V = (V_raw // volume_step) * volume_step`, all as `Decimal`. `entryPrice` is the current executable gateway tick: ask for `BUY`, bid for `SELL`. Gate 7 fails closed with canonical `INVALID_VOLUME` before division when `tick_size`, `tick_value_loss`, `volume_step`, or `volume_min` is missing, non-finite, zero, or negative; it also rejects non-finite or nonpositive `R`, `D`, `L`, `V_raw`, or `V`. Catch `decimal.InvalidOperation` and `decimal.DivisionByZero` and reject with canonical `INVALID_VOLUME`. After downward normalization, it rejects `V < volume_min` with `SIZING_FLOOR_REJECTION` and `V > volume_max` with `INVALID_VOLUME`. Minimum-volume and dust checks are Decimal-only. The invariant is exactly `V * L <= R`; no path may send a volume whose calculated hard-SL loss exceeds the selected risk cash. Convert the normalized volume to `float` exactly once, in the gateway thread while building the final MT5 request.

   Fixed sizing cases are mandatory Decimal fixtures: forex: `equity=10000`, `riskFraction=0.005`, `entryPrice=1.10000`, `stopLoss=1.09500`, `tick_size=0.00001`, `tick_value_loss=1`, `volume_step=0.01`, `volume_min=0.01` yields `R=50`, `L=500`, `V=0.10`; XAU: `equity=10000`, `riskFraction=0.005`, `entryPrice=2300.00`, `stopLoss=2295.00`, `tick_size=0.01`, `tick_value_loss=1`, `volume_step=0.01`, `volume_min=0.01` yields `R=50`, `L=500`, `V=0.10`; BTC: `equity=10000`, `riskFraction=0.005`, `entryPrice=60000.00`, `stopLoss=59500.00`, `tick_size=0.01`, `tick_value_loss=0.01`, `volume_step=0.01`, `volume_min=0.01` yields `R=50`, `L=500`, `V=0.10`.
8. **universal order_check safety asymmetry** — Every broker mutation builds its final MT5 request and calls `order_check` on the gateway thread before `order_send`. Entries require a determinate passing check. Reduce, protection, cancel, and emergency commands may use a best-effort send only when unavailable safety facts or check infrastructure would otherwise block loss-reducing action; an explicit failing `order_check` rejects all commands. Use `ORDER_CHECK_REJECTED` for an explicit negative result.

## 5. Runtime facts interface

Gate evaluation uses an immutable `RuntimeFacts` snapshot supplied by a dedicated interface, not direct MT5 imports or ad hoc globals. It includes monotonic capture time, runtime/entry/halt state, account, bot-magic positions and pending orders, symbol metadata, fresh tick/quote data, exposure and day baseline, active mutation locks, and required configuration revision. The snapshot builder owns freshness and missing-data semantics. It provides no mutation methods.

`PendingOrderFact` has exactly this internal shape: `ticket`, `symbol`, `magic`, `volume`, `orderType`. It is an observation fact, not an SP3 pending-intent or pending-order lifecycle model. The pipeline observes all pending orders; only orders with bot magic are mutable. Foreign pending-order counts remain in parent/bulk summaries untouched and do not become targets or per-item outcomes.

The pipeline captures facts once per command before gates 5–7; the gateway refreshes the final quote, symbol constraints, and `order_check` request immediately before gate 8. Gate 7 must use current gateway-snapshot `equity`, executable tick, and symbol metadata (`tick_size`, `tick_value_loss`, `volume_min`, `volume_max`, `volume_step`) captured together on the gateway thread. Equity freshness uses the configured account freshness budget and tick/metadata freshness uses the configured tick freshness budget; stale, missing, or internally inconsistent fields fail closed for entries with `ENTRY_NOT_ELIGIBLE` before sizing, while invalid sizing metadata fails with `INVALID_VOLUME` at Gate 7. Entry commands reject unavailable required facts. Safety-reducing commands follow gate-8 asymmetry.

## 6. MT5 request mapping and hygiene

Only the injected gateway thread invokes MT5. The gateway owns all MT5 constants through injected module attributes; compatibility fallback values exist only in `gateway.py`. Pipeline modules do not import MT5 constants or call MT5.

The gateway maps commands precisely:

- Entry: `TRADE_ACTION_DEAL`, symbol, side, normalized volume, current executable price, deviation, magic, comment, SL, TP, filling/time policy from symbol metadata.
- Full close and partial close: opposite side `TRADE_ACTION_DEAL`, `position` ticket, current executable price, exact close volume, bot magic, and close comment. Partial close may not leave dust; if remaining volume would be below minimum, close the full position instead.
- Protection update: `TRADE_ACTION_SLTP`, `position` ticket, requested changed protection, preserving the existing broker-side SL or TP when that field is omitted. Never send zero to erase an omitted protection value.
- Pending cancel: `TRADE_ACTION_REMOVE`, `order` ticket.

Every request is rebuilt from current gateway facts; contains only fields valid for that action; excludes `None`, stale payload fields, internal origin, idempotency data, and unrelated position/order fields. Validate price digits, stops/freeze constraints, volume min/max/step, action-specific required ticket, and bot-magic ownership. A broker rejection records `BROKER_REJECTED` with sanitized retcode/comment metadata.

## 7. Gateway seam, timeout, pending intent, uncertainty

The pipeline is a single async consumer. It serializes decisioning; the gateway serializes every MT5 read, `order_check`, `order_send`, and verification on its dedicated thread through a thread-safe command queue. The gateway never awaits asyncio; the asyncio pipeline never blocks on MT5.

Before dispatch, register a pending intent and acquire mutation scope. Await the gateway future through `asyncio.shield` with the configured timeout. Timeout does not cancel the underlying future. On timeout, retain pending intent and lock, transition `TIMED_OUT(GATEWAY_TIMEOUT)`, then perform verification without resend. Disconnect or inconclusive completion transitions `EXECUTION_UNKNOWN` and emits `reconciliation.issue.detected`.

Verification reads only `positions_get`, `order_check`, and `history_deals_get`; it never calls `order_send`. A verified execution emits a resolution event and applies observed state. A verified non-execution releases lock and intent while preserving the original terminal uncertainty record. Indeterminate verification retains both lock and intent, escalates severity, and requires explicit reconciliation. No automatic retry exists.

`PendingIntentRegistry` implements the SP3 lookup seam for close, partial-close, protection, and entry intents. Pending-order cancellation has no SP3 pending lifecycle, lookup, or intent. It is owned by the event loop, never accessed on the gateway thread. Health exposes `mutationInFlight` whenever any scope lock is active.

## 8. Close, cancel, bulk, emergency behavior

Close-all enumerates current bot-magic position targets from gateway facts, acquires per-target scopes, and continues after individual failures. `cancelAll` and emergency cancellation are sweep-only operations: on the gateway thread, call `orders_get` fresh at sweep start, derive bot-magic targets from that result, cancel them, then call `orders_get` fresh again for the required rescan. They never use cached pending-order facts. Each mutable item has its own command outcome metadata; parent/bulk completion reports successful, failed, unknown, skipped, remaining, and observed foreign pending-order counts without changing foreign counts or assigning them item outcomes.

Emergency behavior is strict:

1. Atomically halt entries and persist disabled-entry state before any broker I/O.
2. Emit `safety.kill.started`.
3. Call `orders_get` on the gateway thread; cancel all currently returned bot-magic pending orders, continuing per item.
4. Close all bot-magic positions, continuing per item.
5. Call `orders_get` again on the gateway thread and rescan exactly once after the loops.
6. Emit progress per action and critical alerts for remaining bot-magic stragglers.
7. Emit completed only when the rescan finds no bot-magic stragglers; otherwise emit failed while remaining halted.

Emergency never touches non-bot-magic entities. It remains halted until an explicit start/resume command succeeds under normal control policy.

Exit mapping is exact: operator full close and final partial close emit `MANUAL`; emergency flatten emits `KILL_SWITCH`; observed broker stop-loss and take-profit exits map to `SL` and `TP`; trailing and timed exits map to `TRAIL` and `TIME_EXIT`; breaker exits map to `BREAKER`.

## 9. Configuration

Validated configuration supplies queue size, gateway timeout, entry enablement, freshness budgets, risk budget, loss and exposure limits, volume/dust tolerance, broker-day baseline policy, bot magic, allowed symbols, and emergency behavior. Defaults and units are: `riskFraction` `0.005` as an equity fraction; `maxRiskFraction` `0.01` as an equity fraction; `maxDailyLoss` `0.02` as an equity fraction; `maxTotalVolume` `1` lot; `maxPositions` `5`; tick and account freshness `1000ms`; gateway send timeout `5s`; verification timeout `10s`, requiring at least two polls plus history; and deviation `20` points. The allowed-symbol whitelist is mandatory and fails closed: no entry is tradable unless its symbol is explicitly allowed. Invalid configuration prevents startup. Configuration changes are control commands: journaled, classified, scoped, validated, and reflected in RuntimeFacts before use.

## 10. Required tests

Tests are mandatory; every declared behavior has an executable assertion, including negative and failure paths.

Structural tests prove: canonical `request_json`; atomic creation; replay/conflict no-write behavior; both origins use one pipeline; exact eight-gate order; first-failure short circuit; classification; scope lock conflict/release/retention; entry-only gate exclusion for safety-reducing commands; downward sizing/dust; MT5 action mapping; SL/TP preservation; request hygiene; bot-magic filtering; gateway-thread ownership; `asyncio.shield` timeout; no resend verification; pending intent lifecycle; health mutation state; exact reasons; event/transition sequence; and all exit mappings. Mandatory entry-request tests assert exact `InternalEntryRequest` fields; structural absence of `volume`; `BUY|SELL` only; optional SL, TP, and risk fraction; side-valid SL/TP gate-2 rejection; supplied `price` rejection with `PENDING_ENTRIES_NOT_SUPPORTED`; current tick retrieval on the gateway thread; required `CALIBRATE-SP6` comment; default units and values; risk fraction rejection above `0.01` without clamping; and fail-closed tradable-symbol whitelisting.

End-to-end tests use scriptable MT5 outcomes for entry, close, partial close, protection, cancel, bulk loops, emergency halt-cancel-close-rescan, `order_check` pass/fail/unavailable asymmetry, broker rejection, timeout, late result, disconnect, verified execution, verified non-execution, and unresolved ambiguity. `FakeMt5` scripts bot and foreign pending orders plus a mid-sweep mutation, proving fresh gateway-thread `orders_get` at sweep start and rescan, bot-only mutation, no cached target reuse, and unchanged foreign parent-summary counts. Entry verification tests require a `10s` window, at least two polls, and history. They assert journal rows, SSE event order, locks, intents, observed broker request payloads, and no non-bot-magic mutation.

Sizing tests assert the exact Decimal formulas, `Decimal(str())` conversion at every boundary, no mixed float/Decimal operations, positive-input assertions, the forex/XAU/BTC fixed Decimal fixtures, downward normalization with `(V_raw // volume_step) * volume_step`, Decimal-only minimum/dust checks, `V * L <= R`, canonical `INVALID_VOLUME` rejection for `InvalidOperation` and `DivisionByZero`, and a single float conversion only in the gateway-thread MT5 request. They cover every missing, zero, negative, and non-finite `tick_size`, `tick_value_loss`, `volume_step`, and `volume_min` case with `INVALID_VOLUME`. An optional structural sizing scan may enforce the Decimal boundary and single gateway float-conversion rule. SP3 verification extends `FakeMt5` scriptability to set per-symbol `tick_size`, `tick_value_loss`, `volume_min`, `volume_max`, and `volume_step`, account equity and account/tick/metadata timestamps or monotonic ages, plus atomic gateway snapshot returns, so freshness and mismatched-snapshot failures are deterministic. SP6 calibration checklist must verify broker-specific loss-tick metadata and the forex/XAU/BTC sizing fixtures on each supported broker before enabling entries.

## 11. RCA summary

Prior SP5 material split transport and internal behavior, used obsolete gates, accepted incomplete safety checks, and described timeout paths that could misrepresent broker execution. This specification removes those ambiguities: one ingress pipeline, exact gates, gateway-owned MT5 seam, conservative entry sizing, asymmetric loss-reduction safety, durable scope/pending state, and verification without resend.

## 12. Self-review

- Exactly eight gates, names and order match section 4.
- No legacy gate names, deferred implementation, or incomplete normative behavior.
- Idempotency, origins, atomic journal creation, request fingerprint conflicts, runtime facts, MT5 request mappings, uncertainty handling, emergency behavior, health, config, events, reasons, structural tests, and end-to-end tests are normative.
- This file is complete implementation authority for backend SP5.
