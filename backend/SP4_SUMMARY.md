# SP4 Summary — FastAPI & Web Server Transport

**Date:** 2026-07-13  
**Status:** COMPLETE — 189/189 tests pass, SP1–SP3 remain green.

**PROTOCOL-NOTE:** Commit `e76c40a` was an out-of-protocol design-only commit containing only `backend/SP4_DESIGN.md` (`git show --stat e76c40a`: one documentation file, zero source/test/config changes). SP4 acceptance applies solely to the green implementation checkpoint commit that follows.

---

## RCA: What Was Wrong in the Partial SP4

### 1. Wrong route census (critical)

The partial implementation used SP4_DESIGN §2 as its source instead of the **authoritative** HANDOFF.md §10.1 endpoint table. This produced:

| Wrong (partial) | Correct (§10.1) |
|---|---|
| `POST /v4/command` (singular) | `POST /v4/commands` |
| `GET /v4/journal/session` | removed — not in §10.1 |
| `GET /v4/journal/calendars` | removed — not in §10.1 |
| `GET /v4/journal/trades` | removed — not in §10.1 |
| `GET /v4/stream` | `GET /v4/events/stream` |
| missing `GET /v4/capabilities` | added |
| missing `GET /v4/commands/{commandId}` | added |
| missing `GET /v4/history/trades` | added |

`/v4/ops/metrics` is not in §10.1 but explicitly required by SP4_DESIGN §2.2 — retained.

### 2. Handshake returned wrong shape

`/v4/handshake` returned the `EXPECTED_RUNTIME_CONTRACT` object (frontend verification payload) rather than the `RuntimeHandshake` interface that the backend declares. HANDOFF §10.2 is explicit: the response is `RuntimeHandshake` with `runtimeId`, `bootId`, `runtimeVersion`, `capabilitiesRevision`, `supportedCommands`, `supportedFeatures`, `observedAt`, `source`.

### 3. SSE subscribe/ping ordering race

The generator yielded the initial `":\n\n"` ping **before** subscribing to the EventBus. Any event published between `anext(gen)` returning the ping and the next `anext` call was silently dropped. Fix: subscribe under `_publish_lock` first, then yield the ping.

### 4. Idempotency not atomic

The partial `command.py` did a read then write as two separate operations, creating a TOCTOU window. Fix: use `journal.try_insert_command_create` which performs the idempotency check, event insert, command upsert, and transition insert inside a single writer-thread transaction, returning `(status, created: bool)`.

### 5. Conftest async fixture dependency broken

`app_client` was a sync `TestClient` fixture that depended on the async `event_bus` fixture — pytest-asyncio cannot inject async fixtures into sync fixtures. Replaced all fixtures with `AsyncClient` + `httpx.ASGITransport` throughout.

### 6. Missing security module

Token verification logic was duplicated inline in `stream.py`. Extracted to `web/security.py` and applied uniformly across all authenticated routes.

---

## Protocol Notes

### Race-Free Splice (§3.2) — invariant

SP2 enforces: **SQLite commit MUST complete before EventBus publish**. This is the precondition for gap-free replay. `EventBus.publish` and `publish_command_event` both hold `_publish_lock` for the entire commit+fanout sequence. The SSE handoff subscribes under the same lock, capturing `boundary = bus.sequence` atomically. Replay queries `journal WHERE sequence > snapshot_sequence AND sequence <= boundary`. Live queue discards `sequence <= boundary`. Result: no gap, no duplicate.

### bootId lifecycle

`bootId` changes on every `EventBus.start()`. Resume identity is carried by the transport-layer `bootId` query parameter because `Last-Event-ID` contains only a sequence. A mismatched boot emits `BOOT_ID_CHANGED` without replay, including the numeric-overlap trap. A resume header without `bootId` emits `BOOT_ID_UNKNOWN`. Fresh attachment without `Last-Event-ID` starts live without replay.

### Control frame reasons

`system.resync.required` is a non-envelope SSE control frame per HANDOFF §10.5. It is deliberately absent from `RUNTIME_EVENT_TYPES`, never journaled, and has no `id:` line. Reasons are `BOOT_ID_CHANGED`, `BOOT_ID_UNKNOWN`, `SEQUENCE_UNAVAILABLE`, and `SUBSCRIBER_LAGGING`; data also carries current `bootId` and `currentSequence`. The connection remains open. The future frontend `SseRuntimeEventSource` must treat this as a transport control frame, not a runtime envelope.

### SSE frame format (§10.5)

```
id: <sequence>\n
event: <type>\n
data: <JSON envelope>\n
\n
```

`id` equals envelope `sequence` (monotonic per `bootId`). The frontend uses `Last-Event-ID` header on reconnect; the server resumes from `sequence + 1` if available, else emits `system.resync.required`.

### Command idempotency (§10.4)

Identical `idempotencyKey` returns the identical existing record and journals nothing new. Execution-implying commands follow deterministic `command.created` → `command.accepted` → `command.failed`; SP4 refuses execution with the canonical SP4 reason and performs no MT5 mutation.

### Sign convention (HANDOFF §Phase 5F.5)

`commission` and `swap` are SIGNED. `netPnl = grossPnl + commission + swap` (addition, never subtraction). SP4 has no closed trades yet but the `ClosedTrade` model in `contract/models.py` enforces this shape.

---

## Files Changed / Created

### New
- `backend/src/metascan/web/security.py` — token verification (Bearer + ?token=)
- `backend/src/metascan/web/routers/capabilities.py` — `GET /v4/capabilities`
- `backend/src/metascan/web/routers/snapshot.py` — `GET /v4/snapshot`
- `backend/src/metascan/web/routers/commands.py` — `POST /v4/commands`, `GET /v4/commands/{commandId}`
- `backend/src/metascan/web/routers/stream.py` — `GET /v4/events/stream`
- `backend/src/metascan/web/routers/history.py` — `GET /v4/history/trades`

### Rewritten
- `backend/src/metascan/web/app.py` — route census matches §10.1 exactly
- `backend/src/metascan/web/dependencies.py` — clean stubs
- `backend/src/metascan/web/sse.py` — subscribe-before-ping ordering fix, 4-reason control frames
- `backend/src/metascan/web/routers/handshake.py` — correct `RuntimeHandshake` shape
- `backend/src/metascan/web/routers/health.py` — pure SLO + ops metrics
- `backend/tests/test_web/conftest.py` — async fixtures throughout
- `backend/tests/test_web/test_api_handshake.py`
- `backend/tests/test_web/test_api_health.py`
- `backend/tests/test_web/test_api_commands.py`
- `backend/tests/test_web/test_api_journal.py` — renamed to history/trades tests
- `backend/tests/test_web/test_api_sse.py`
- `backend/tests/test_web/test_api_lifecycle.py`

### Deleted (dead files)
- `backend/src/metascan/web/routers/command.py` — superseded by `commands.py` (plural, correct path)
- `backend/src/metascan/web/routers/journal.py` — `/v4/journal/*` routes not in §10.1

### Removed (routes, not files)
- `GET /v4/journal/session`
- `GET /v4/journal/calendars`
- `GET /v4/journal/trades`
- `POST /v4/command` (singular)
- `GET /v4/stream`

---

## Verification

```
189 passed, 1 warning in 12.03s
```

SP1–SP3 test count unchanged (126 → 126). SP4 web tests: 63 total (40 prior + 23 quality blockers), all green.

---

## Code-Quality Blocker Fixes (2026-07-13)

### Item 1 — Global 500 never exposes `str(exc)`
`app.py` exception handler stripped `"details": str(exc)`. Response is now static `{"error": "Internal Server Error", "code": "INTERNAL_ERROR"}` only. Test: `test_global_500_no_exc_details`.

### Item 2 — `hmac.compare_digest` auth + sentinel return
`security.py` replaced `token != expected` with `hmac.compare_digest(token.encode(), expected.encode())` to prevent timing-oracle attacks. `verify_token` now returns opaque sentinel `"AUTHENTICATED"` instead of the raw token — handler signatures never carry secret material. Tests: `test_auth_hmac_used`, `test_auth_returns_sentinel_not_token`, `test_auth_sentinel_not_raw_token`.

### Item 3 — `SEQUENCE_UNAVAILABLE` control frame
`sse.py` guards replay distance against `READ_EVENTS_HARD_CAP` (10 000). When `replay_limit > READ_EVENTS_HARD_CAP`, emits `system.resync.required` with reason `SEQUENCE_UNAVAILABLE` instead of attempting the query (which would raise `ValueError`) or falling into `INTERNAL_ERROR`. `SEQUENCE_UNAVAILABLE` added to `_RESYNC_REASONS` frozenset. Tests: `test_sequence_unavailable_reason_in_allowed_set`, `test_sequence_unavailable_emitted_when_replay_exceeds_cap`, `test_no_internal_error_for_large_replay`.

### Item 4 — Transition sequence == stamped event sequence
`commands.py` was pre-building `CommandTransitionRecord(sequence=bus.sequence)` (pre-stamp, value 0) and calling `try_insert_command_create` to commit it, then calling `publish_command_event` which stamped a new sequence and committed again — producing a mismatch. Fix: removed pre-built transition and `try_insert_command_create` entirely. `publish_command_event` now handles the full atomic commit: stamps envelope inside `_publish_lock`, builds `CommandTransitionRecord(sequence=stamped.sequence)`, commits bundle, then fanouts. Single DB write path guarantees `transition.sequence == event.sequence`. Tests: `test_command_transition_sequence_equals_event_sequence`, `test_command_transition_sequence_nonzero`.

### Item 5 — `/history/trades` real journal query
`history.py` replaced stub with real SQLite query: `SELECT sequence, envelope_json FROM events WHERE type = 'trade.closed' ORDER BY sequence DESC LIMIT ?`. Cursor is opaque base-10 string encoding last-seen sequence (exclusive upper bound). Returns `TradeHistoryPage` shape per §10.6. Tests: `test_history_trades_returns_journal_data`, `test_history_trades_cursor_pagination`, `test_history_trades_no_non_trade_events`.

### Item 6 — `activeSseConnections` real counter
`sse.py` adds `SseConnectionCounter` (thread-safe, floor-zero decrement) as module-level singleton `active_sse_connections`. `SseHandoff.generate_stream` calls `increment()` before first yield and `decrement()` in `finally`. `health.py` `get_metrics` reads `active_sse_connections.count`. Tests: `test_sse_counter_increments_on_connect`, `test_sse_counter_decrement_floor_zero`, `test_ops_metrics_active_sse_count`, `test_sse_handoff_increments_counter`.

### Item 7 — `GatewayMetrics.note_cycle_overrun` locked
`metrics.py` adds `note_cycle_overrun()` (increments `cycle_overruns` under `_lock`) and `snapshot()` (consistent point-in-time copy under lock). Direct bare increment `m.cycle_overruns += 1` replaced by callers using the locked helper. Tests: `test_gateway_metrics_note_cycle_overrun`, `test_gateway_metrics_note_cycle_overrun_concurrent` (100 threads), `test_gateway_metrics_snapshot_consistent`.

### Item 8 — EventBus unsubscribe/close race
`unsubscribe()` is a plain `dict.pop` — no lock. SSE `finally` calls it without acquiring `_publish_lock`, so no deadlock when `_fanout` holds the lock. `generate_stream` refactored: subscribe+boundary capture under lock first, then yields ping, then delegates to `_stream_body` generator, `finally` decrements counter and unsubscribes. Tests: `test_sse_unsubscribe_no_deadlock_during_publish`, `test_bus_close_unsubscribes_cleanly`, `test_unsubscribe_idempotent`.

Note: EventBus commit-before-fanout lock scope unchanged per SP2/reviewer I8 ruling.

### New file
- `backend/tests/test_web/test_sp4_quality.py` — 23 tests covering all 8 items
