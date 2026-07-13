# SP5 Summary: Command Pipeline + RiskGate + MT5 Mutation Seam

**Status:** Implemented and verified. **Date:** 2026-07-14. **Tests:** 269 passed, 0 failed.

---

## Delivered Scope

1. **Single ingress pipeline** — `CommandPipeline` (single asyncio task) consumes from bounded queue. Both origins (`TRANSPORT`, `INTERNAL`) share one lifecycle, locking, safety classification, and outcome handling. No deferred ingress split.

2. **8 ordered RiskGates** — Exact names, order, and reasons per `SP5_DESIGN.md` section 4:
   1. idempotency
   2. validation
   3. safety classification
   4. mutation scope lock
   5. entry-only eligibility
   6. entry-only exposure
   7. entry-only hard-SL+risk sizing downward floor
   8. universal order_check safety asymmetry

   First failure short-circuits. Entry-only gates skipped for reduce/protection/cancel/control/emergency commands. Gate 8 asymmetry: reduce commands may proceed when order_check is unavailable; explicit rejections fail all commands.

3. **Lifecycle** — `PREPARED → SUBMITTING → ACCEPTED → IN_PROGRESS → COMPLETED | FAILED | EXECUTION_UNKNOWN`. Await-side timeout or ambiguous broker result transitions directly to `EXECUTION_UNKNOWN`; no blind retry and no `TIMED_OUT` detour. `SUBMITTING` is journaled without SSE. Transition sequence equals event envelope sequence.

4. **Canonical reasons** — Exactly per SP5_DESIGN.md section 3 table. No `Deferred`, no `TIMED_OUT` as standalone (now `EXECUTION_UNKNOWN` with `GATEWAY_TIMEOUT` → direct `EXECUTION_UNKNOWN`), no `PARTIAL_FINAL` exit reason emitted by pipeline (R18: `position.closePartial` has no exit reason — SP3 consumer emits `position.partially_closed`).

5. **Gateway seam** — `Mt5Gateway._cmd_queue` (thread-safe `queue.Queue`), drained at top of each poll cycle on gateway thread. `submit_command(fn)` returns `concurrent.futures.Future`. Pipeline awaits via `asyncio.shield` + `asyncio.wait_for` with configured timeout. Timeout does not cancel underlying future.

6. **PendingIntentRegistry** — Implements SP3 `PendingIntentLookup` Protocol. Registers close/partial/modify/entry intents on ACCEPTED. Clears on terminal. Retains on EXECUTION_UNKNOWN. Asyncio-only.

7. **Uncertainty** — Await-side timeout never cancels the gateway future. The command enters `EXECUTION_UNKNOWN`, retains its scope lock and intent, and verifies broker facts without resending. Proven execution completes; proven non-execution fails and releases; unresolved verification fails with `VERIFICATION_UNRESOLVED`, emits `alert.created` CRITICAL, and retains lock/intent for SP7.

8. **Exit reasons** — `position.close` → `MANUAL`, `runtime.emergencyKill` → `KILL_SWITCH`. `position.closePartial` → no exit reason (SP3 consumer handles partial close event). Broker SL/TP hits detected by SP3 as external closes; SP7 retroactively reclassifies.

9. **Emergency behavior** — Atomically halt entries, persist disabled state, emit `safety.kill.started`, sweep-cancel all bot-magic orders (fresh `orders_get`), close all bot-magic positions, rescan, emit progress/failed/completed with straggler counts.

10. **R18 partial close** — `_normalize_partial` uses `Decimal(str())` at every boundary. Floor-exact to `volume_step`. Rejects `requested < volume_min` with `PARTIAL_CLOSE_BELOW_MIN_VOLUME`. Rejects remainder `0 < r < volume_min` with `PARTIAL_CLOSE_DUST_REMAINDER`. Never auto-full-closes. Full close rereads current volume from fresh `mt5.positions_get()` on gateway thread.

11. **InternalEntryRequest** — `symbol`, `side` (BUY|SELL), optional `stopLoss`, optional `takeProfit`, optional `riskFraction`. `volume` structurally absent. `price` rejected with `PENDING_ENTRIES_NOT_SUPPORTED`. Current tick obtained on gateway thread. Comment includes `CALIBRATE-SP6`.

12. **FakeMt5** — `order_send()` with scriptable outcomes, timeout trigger, disconnect trigger. `order_check()` with scriptable pass/fail/none. `sweep_facts()` returning fresh orders/positions. Per-symbol volume/equity manipulation.

---

## RCA: Why Design Ignored Prior Plan

Prior SP5 plan (`SP5_PLAN.md`) described 8 old-style gates with different names and ordering (KillSwitch, RuntimeState, DataFreshness, HardSl, Sizing, SpreadGuard, Exposure, Freeze), used `GateContext` with runtime state strings, had `TIMED_OUT` as standalone state, included `PARTIAL_FINAL` as closePartial exit reason, and auto-full-closed on dust remainder. The authoritative `SP5_DESIGN.md` replaced all of this with: exact 8-gate names, Decimal-only sizing, entry-only gate exclusion, unified ingress, gateway-thread-owned mutation, and deterministic partial close rejection. Implementation follows `SP5_DESIGN.md` as sole authority.

---

## Emergency Composition

`runtime.emergencyKill`:
1. Set `halted=True`, `entries_enabled=False`, persist to runtime_state table
2. Emit `safety.kill.started` (INFO)
3. Sweep `orders_get` on gateway thread → cancel all bot-magic orders (per-item continue)
4. Emit `safety.kill.progress` (phase: "ordersCancelled")
5. Sweep `positions_get` on gateway thread → close all bot-magic positions (per-item continue)
6. Emit `safety.kill.progress` (phase: "positionsClosed")
7. Rescan: fresh `orders_get` + `positions_get`
8. Stragglers found → emit `safety.kill.failed` (CRITICAL) with straggler IDs
9. No stragglers → emit `safety.kill.completed` (INFO)

---

## One-Entry-Per-Symbol

Entry scope locks are `entry:{symbol}`. Only one entry per symbol may be in-flight. Lock released on terminal outcome or verified reconciliation. No multi-entry-per-symbol pipeline support.

---

## Phase 2 Command-Status Enum Contract Note

`RuntimeCommandStatus` is a pure transport enum. It contains no `origin`, `execution_kind`, or internal identity fields. Phase 2 contract: REST remains transport/query only; internal entry identity represented exclusively by persisted `origin=INTERNAL` and `execution_kind=INTERNAL_ENTRY_MARKET`; event payloads retain command `kind` passthrough; absent internal command IDs are REST 404s.

---

## SP7 SL/TP Caveat

SL/TP hits on broker side are detected by SP3 as external closes (ticket disappears). SP3 emits `exitReason=MANUAL` because it cannot distinguish broker-SL-hit from operator-close without deal history. SP7 history backstop will retroactively reclassify those `trade.closed` events. SP5 does not change this behavior.

---

## Correlation Query

```sql
SELECT
    c.command_id, c.kind, c.state,
    t.from_state, t.to_state, t.ts,
    e.type AS event_type,
    e.sequence AS event_sequence,
    t.sequence AS transition_sequence,
    CASE WHEN e.sequence = t.sequence THEN 'ok' ELSE 'MISMATCH' END AS seq_check
FROM commands c
JOIN command_transitions t ON t.command_id = c.command_id
JOIN events e ON e.boot_id = t.boot_id AND e.sequence = t.sequence
WHERE c.idempotency_key = ?
ORDER BY t.ts;
```

---

## R1-R26 Coverage

| Req | Description | Status |
|-----|-------------|--------|
| R1 | Single ingress pipeline | DONE |
| R2 | TRANSPORT/INTERNAL origins | DONE |
| R3 | Idempotency (replay/conflict/new) | DONE |
| R4 | Lifecycle states + transitions | DONE |
| R5 | 8 ordered gates | DONE |
| R6 | Entry-only gate exclusion | DONE |
| R7 | Decimal sizing downward floor | DONE |
| R8 | Gateway thread ownership | DONE |
| R9 | order_check safety asymmetry | DONE |
| R10 | PendingIntentRegistry | DONE |
| R11 | EXECUTION_UNKNOWN terminal, no retry | DONE |
| R12 | Verification without resend | DONE |
| R13 | Emergency kill-cancel-close-rescan | DONE |
| R14 | Close-all / cancel-all bulk | DONE |
| R15 | Exit reason mapping | DONE |
| R16 | FakeMt5 scriptable outcomes | DONE |
| R17 | mutationInFlight health | DONE |
| R18 | Partial close dust rejection | DONE |
| R19 | RuntimeFacts snapshot interface | DONE |
| R20 | InternalEntryRequest volume-absent | DONE |
| R21 | PendingOrderFact observation | DONE |
| R22 | Unsupported → FAILED, unknown → 422 | DONE |
| R23 | SUBMITTING journaled, no SSE | DONE |
| R24 | asyncio.shield timeout | DONE |
| R25 | Transition sequence invariant | DONE |
| R26 | Correlation query | DONE |

---

## Test Count

269 tests, 0 failures, 1 warning (starlette deprecation, unrelated).

---

## Files

### New
- `src/metascan/pipeline/__init__.py`
- `src/metascan/pipeline/risk_config.py`
- `src/metascan/pipeline/risk_gate.py`
- `src/metascan/pipeline/command_queue.py`
- `src/metascan/pipeline/pending_intent.py`
- `src/metascan/pipeline/dispatcher.py`
- `src/metascan/pipeline/outcome_handler.py`
- `src/metascan/pipeline/command_pipeline.py`
- `src/metascan/pipeline/request.py`
- `src/metascan/pipeline/facts.py`
- `tests/test_pipeline/` (empty directory, pipeline tests live in `tests/test_sp5_*.py`)

### Modified
- `src/metascan/mt5/gateway.py` — command queue + submit_command + _drain_commands + _normalize_partial (Decimal)
- `src/metascan/mt5/testing/fake_mt5.py` — order_send + scriptable outcomes + sweep_facts
- `src/metascan/web/routers/commands.py` — PREPARED state, command.created, pipeline enqueue
- `src/metascan/web/dependencies.py` — get_pipeline, get_risk_config
- `tests/test_web/conftest.py` — pipeline_stub fixture
- `tests/test_web/test_api_commands.py` — updated state assertions
- `tests/test_web/test_sp4_quality.py` — updated event type query
