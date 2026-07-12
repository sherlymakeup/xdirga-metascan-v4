# XDIRGA METASCAN — Backend Handoff (Phase 5F.4)

> Audience: authors of the local **XDirga Runtime V4** backend (the
> `LOCAL_RUNTIME` frontend data source). This document is the authoritative
> contract the frontend already enforces. Anything not listed here is not
> guaranteed by the UI.

---

## 1. Identity model

The frontend distinguishes **frontend data source** from **broker environment**
and never conflates them:

| Concept                | Values                                        | Owned by         |
| ---------------------- | --------------------------------------------- | ---------------- |
| `FrontendDataSource`   | `DEVELOPMENT_FIXTURE` \| `LOCAL_RUNTIME`      | frontend         |
| `BrokerEnvironment`    | `TRIAL` \| `LIVE`                             | runtime + broker |
| `RuntimeMode`          | `FIXTURE` \| `LIVE`                           | derived          |

`DEVELOPMENT_FIXTURE` is a deterministic in-browser simulator used until a
local runtime is reachable. It must **never** be presented as if it were a
live runtime. The frontend refuses to silently fall back to fixture data.

---

## 2. Adapter contract

All adapters implement `RuntimeAdapter` (see `src/lib/runtime/runtime-adapter.ts`).
`getDescriptor()` returns the truthful identity strip consumed by the UI:

```ts
{ source, mode, brokerEnvironment, connection, target }
```

`connection` is one of `CONNECTED | CONNECTING | DISCONNECTED | UNAVAILABLE`.
The HTTP adapter (`http-runtime-adapter.ts`) must **never throw** from
`getOperator()`, `getCapabilities()`, or `getDescriptor()` — when disconnected
it returns a deterministic `VIEWER` identity with all capabilities `allowed:
false`. This keeps the component tree crash-safe when the runtime is down.

---

## 3. Handshake & capabilities

See `runtime-contract.ts` + `runtime-handshake.ts`.

- `protocolId` MUST equal `RUNTIME_CONTRACT.protocolId`.
- `protocolVersion` is semver-checked; major mismatch → **SAFE MODE**.
- `schemaHash` mismatch → **SAFE MODE** (all capabilities forced to
  `allowed: false` except safety commands).
- Capability payloads must enumerate every `RuntimeCommandKind` the runtime
  supports; unknown kinds render as disabled in the UI.

Safety command allow-list (never blocked, even in SAFE MODE):
`safety.kill`, `runtime.pause`, `runtime.disableEntries`,
`position.close`, `order.cancel`.

---

## 4. Command orchestration

`commandOrchestrator.submitCommand` is the single entry point. Every command
is gated in this order:

1. Connection (adapter descriptor)
2. Handshake / SAFE MODE
3. Role (`operator-role.ts` — VIEWER / OPERATOR / RISK_MANAGER / ADMIN)
4. Freshness (`freshness-policy.ts`)
5. Reconciliation restrictions (`reconciliation-restrictions.ts`)
6. `EXECUTION_UNKNOWN` per-entity locks (`execution-unknown-lock.ts`)
7. Idempotency (`command-equivalence.ts` → equivalence key = idempotency key)
8. Transition validation (`command-transitions.ts`)

The runtime **must** accept the idempotency key and treat re-submissions of an
in-flight command as no-ops that return the existing command handle.

### Command lifecycle

Runtime status updates MUST follow the transition table in
`commands/command-transitions.ts`. Invalid transitions are dropped by the UI
and surfaced as `system.validation.failed` events. Terminal states:
`COMPLETED | FAILED | TIMED_OUT | EXECUTION_UNKNOWN | CANCELLED`.

`EXECUTION_UNKNOWN` on order/position/command events **must** carry the
affected entity id; the frontend uses it to lock the entity from further
commands until `reconciliation.issue.resolved` fires for the same id.

---

## 5. Event stream

Envelope: `src/lib/runtime/events/runtime-event-envelope.ts` — authoritative,
Zod-validated at the boundary. Every event MUST include:

- `eventId` (globally unique)
- `runtimeId`, `bootId` (bootId changes on runtime restart → resets dedup cursor)
- `revision`, `sequence` (monotonic per `(runtimeId, bootId)`; gaps → `system.event_gap.detected`)
- `occurredAt`, `emittedAt` (ISO-8601 UTC)
- `severity`, `source`, typed `payload`

Event type union is closed — see `RUNTIME_EVENT_TYPES`. Any unknown type
fails validation and is emitted as `system.validation.failed`.

Deduplication semantics are enforced by `EventDeduplicator`:
- Duplicate `eventId` → drop
- Older sequence than cursor → drop
- Older `bootId` → drop as `obsolete-boot`
- Newer `bootId` → cursor reset

The runtime is expected to emit a bootstrap `runtime.state.changed` event
with the new `bootId` on every restart before any domain events.

---

## 6. Snapshot hydration

`snapshot-hydration.ts` performs **atomic** hydration: the runtime provides a
snapshot for `(runtimeId, bootId, revision)`; the frontend replays events
with `revision > snapshot.revision` on top. During hydration the UI shows the
`HYDRATING` operational state and blocks command submission.

Snapshots MUST be self-consistent (no half-written orders/positions) and
carry the same `revision` that will appear on the next event so the
convergence tracker (`state/convergence.ts`) can verify no drift.

---

## 7. Notifications

`events/notification-policy.ts` decides toast vs persistent vs silent. The
runtime doesn't need to know about UI presentation — it only needs to emit
events with correct `type` and `severity`. Critical types always escalate
regardless of `severity`:

`command.execution_unknown`, `order.execution_unknown`,
`position.execution_unknown`, `position.unprotected`,
`safety.circuit_breaker.opened`, `safety.kill.failed`,
`runtime.safe_mode.changed`, `reconciliation.failed`,
`system.event_gap.detected`.

---

## 8. Production guards

`DEVELOPMENT_FEATURES_ENABLED` (see `dev-flags.ts`) gates fixture controls,
mode selector, and diagnostic panels. In a production build:

- Fixture adapter cannot be selected from the UI.
- Fixture warning banner (`ProdFixtureGuard`) is shown if fixture mode is
  ever active.
- `system.tsx` diagnostic panels are hidden.

---

## 9. Test coverage

`src/lib/runtime/__tests__/` covers the pure contract logic:

| Suite                          | Guards                                          |
| ------------------------------ | ----------------------------------------------- |
| `command-equivalence.test.ts`  | idempotency key derivation                      |
| `command-transitions.test.ts`  | state machine, terminal states                  |
| `freshness-policy.test.ts`     | classification + safety-command allow-list      |
| `event-deduplicator.test.ts`   | seq gap, boot reset, obsolete-boot rejection    |
| `notification-policy.test.ts`  | CRITICAL escalation, silent-type filtering      |

Run: `bunx vitest run src/lib/runtime/__tests__`.

Any backend change that alters these contracts **must** update the
corresponding pure module + test in the same change.

---

## Phase 5F.5 — v4.1 additions (final contract shape)

### Transport: REST + SSE (WebSocket is NOT supported)

* Everything is REST + Server-Sent Events. There is no WebSocket surface.
* REST auth: `Authorization: Bearer <token>`.
* SSE auth: the token is passed as `?token=<token>` on the stream URL because
  `EventSource` cannot set custom headers. The backend MUST accept the token
  from BOTH transports on the SAME identity.
* SSE stream path: `${baseUrl}${eventStreamPath}` where `eventStreamPath`
  defaults to `/events/stream`.

### Sign convention (commission, swap, netPnl)

`commission` and `swap` are SIGNED values reported exactly as MT5 returns
them. Broker COSTS are NEGATIVE, credits are POSITIVE. The following
identity MUST hold on every `Position` and every `ClosedTrade`:

```
netPnl = grossPnl + commission + swap    (closed trade)
netPnl = floatingPnl + commission + swap (open position)
```

Addition — never subtraction. Enforced by fixtures and covered by
`src/lib/runtime/__tests__/sign-convention.test.ts`.

### Trade Journal cache semantics

* Cache is bounded to the 500 most-recent closed trades; older rows are
  fetched from `RuntimeAdapter.getTradeHistory({ cursor, limit })`.
* Dedup key: `tradeId`. On conflict, the LIVE `trade.closed` EVENT WINS
  over any paginated backfill row for the same id. Once a tradeId has been
  seen via an event, later `getTradeHistory` pages MUST NOT overwrite it.
* See `src/lib/runtime/domain/trade-journal.ts` + `trade-journal.test.ts`.

### R-multiple null handling

* Trades with `rMultiple === null` are EXCLUDED from the R-multiple
  histogram and from `avgR`.
* They ARE counted in trade totals (`total`, `netPnl`, `wins/losses`).
* The Analytics summary strip surfaces an explicit `n/a R excluded` count so
  nothing silently disappears.

### Position Autopilot Management

* Every open `Position` carries a `management` field (`PositionManagement | null`).
* Autopilot plan components: `breakEven`, `trailing`, `partialTp`, `timeExit`.
* Operator commands:
  * `position.management.pause` — pause autopilot for a single position.
  * `position.management.resume` — resume autopilot for a single position.
* Live events under `position.management.*` update the plan in place and
  are projected into `Position.management` via the domain projections.

---

## 10. REST + SSE Endpoint Registry (authoritative)

All endpoints are namespaced under `/v4/`. REST requests carry
`Authorization: Bearer <token>` and `Content-Type: application/json`. The
SSE stream carries the SAME token via `?token=<token>` query parameter
because `EventSource` cannot set custom headers — the backend MUST accept
either transport for the same identity token.

Base URL is configured on the frontend adapter; the paths below are the
paths the frontend calls, unmodified.

### 10.1 Endpoint table

| Method | Path                            | Purpose                                   | Auth        |
| ------ | ------------------------------- | ----------------------------------------- | ----------- |
| GET    | `/v4/handshake`                 | Protocol identity + schema hash           | Bearer      |
| GET    | `/v4/capabilities`              | Allowed commands + feature flags          | Bearer      |
| GET    | `/v4/snapshot`                  | Atomic `CockpitSnapshot` envelope         | Bearer      |
| POST   | `/v4/commands`                  | Submit a command (idempotent)             | Bearer      |
| GET    | `/v4/commands/{commandId}`      | Poll a single command status              | Bearer      |
| GET    | `/v4/events/stream`             | SSE event stream (see §10.5)              | `?token=`   |
| GET    | `/v4/history/trades`            | Paginated closed-trade history            | Bearer      |
| GET    | `/v4/health`                    | Liveness/readiness probe                  | Bearer      |

### 10.2 `GET /v4/handshake`

Response: `RuntimeHandshake` (see `runtime-types.ts`).

Required fields: `runtimeName`, `protocolId` (must equal
`xdirga-runtime-v4`), `protocolVersion`, `schemaVersion`, `schemaHash`,
`minFrontendVersion`, `brokerProvider`, `brokerEnvironment`,
`executionSemantics`, `capabilitiesFingerprint`.

The frontend rejects mismatches per §6 (SAFE MODE lockout).

### 10.3 `GET /v4/snapshot`

Response: `RuntimeSnapshotEnvelope { snapshot: CockpitSnapshot, revision, bootId, generatedAt }`.

Snapshot is atomic. Partial snapshots are forbidden — the frontend replaces
its authoritative state wholesale on receipt.

### 10.4 `POST /v4/commands`

Request body:

```
{
  "kind": "<RuntimeCommandKind>",
  "params": { ... },
  "idempotencyKey": "<client-generated>",
  "correlationId": "<optional>",
  "operatorId": "<optional>"
}
```

Response: `CommandAccepted { commandId, state, receivedAt, idempotencyKey }`.

Replay semantics: an identical `idempotencyKey` received again within the
retention window MUST return the SAME `commandId` and current state — no
new command is created. See `command-equivalence.ts`.

### 10.5 `GET /v4/events/stream` (SSE)

* Content-Type: `text/event-stream`.
* Each SSE frame:
  * `id:` MUST equal the envelope `sequence` (monotonic per `bootId`).
  * `event:` MUST equal the envelope `type`.
  * `data:` is the JSON-encoded `RuntimeEventEnvelope`.
* Reconnect: the frontend sends `Last-Event-ID: <last sequence>`. The server
  MUST resume from `sequence + 1` if still available, otherwise emit
  `system.resync.required` and the frontend refetches `/v4/snapshot`.
* Auth: token via `?token=`. No cookies.

### 10.6 `GET /v4/history/trades?cursor=&limit=`

Response: `TradeHistoryPage { trades: ClosedTrade[], nextCursor: string | null }`.

Cursor is opaque; the frontend passes it back unchanged. `limit` default 100,
max 500. See §"Trade Journal cache semantics" for dedup rules.

### 10.7 `GET /v4/health`

Response `{ status: "OK" | "DEGRADED" | "DOWN", detail?: string }`. Used for
UI connection heartbeat only — never for capability decisions.

### 10.8 Command kinds (authoritative)

Required kinds. Payload schema names refer to the Zod payload shapes in
`src/lib/runtime/events/event-schemas.ts` and the command-param schemas the
backend MUST accept:

| Kind                              | Notes                              |
| --------------------------------- | ---------------------------------- |
| `runtime.start`                   | idempotent                         |
| `runtime.pause`                   | safety-critical                    |
| `runtime.resume`                  |                                    |
| `runtime.emergencyKill`           | safety-critical                    |
| `runtime.disableEntries`          | safety-critical                    |
| `runtime.reconnectBroker`         |                                    |
| `runtime.reconcile`               |                                    |
| `strategy.pause`                  | `{ strategyId }`                   |
| `strategy.resume`                 | `{ strategyId }`                   |
| `order.cancel`                    | `{ orderId }`                      |
| `order.cancelAll`                 | safety-critical                    |
| `position.close`                  | `{ positionId }`                   |
| `position.closeAll`               | safety-critical                    |
| `position.management.pause`       | `{ positionId }`                   |
| `position.management.resume`      | `{ positionId }`                   |
| `breaker.reset`                   | `{ key }`                          |
| `config.validate`                 | `{ configBlob }`                   |
| `config.apply`                    | `{ configBlob }`                   |
| `config.rollback`                 |                                    |
| `alert.acknowledge`               | `{ alertId }`                      |
| `incident.acknowledge`            | `{ incidentId }`                   |

### 10.9 Event types (authoritative)

The full event catalog is enumerated in
`src/lib/runtime/events/runtime-event-envelope.ts` (`runtimeEventTypeSchema`).
Backends MUST NOT emit unknown types — the envelope validator rejects them.

Payload schema names (see `event-schemas.ts`):

| Type prefix                             | Payload schema                              |
| --------------------------------------- | ------------------------------------------- |
| `command.*`                             | `{ commandId, state?, message?, reason? }`  |
| `order.*`                               | `{ orderId, status?, symbol? }`             |
| `position.management.plan_changed`      | `planChangedPayloadSchema`                  |
| `position.management.action_executed`   | `actionExecutedPayloadSchema` (discriminated on `action`) |
| `position.management.action_failed`     | `actionFailedPayloadSchema`                 |
| `position.*` (other)                    | `{ positionId, protection?, symbol? }`      |
| `trade.closed`                          | Closed-trade payload (signed cost identity) |
| `strategy.*`                            | `{ strategyId }`                            |
| `safety.circuit_breaker.*`              | `{ key, state? }`                           |
| `reconciliation.*`                      | `{ reconciliationRunId? }`                  |
| `risk.limit.*`                          | `{ key, value?, threshold? }`               |
| `system.event_gap.*`                    | `{ from, to, missing }`                     |

### 10.10 Position management action enum

Authoritative spelling — must match `MANAGEMENT_ACTIONS` in
`event-schemas.ts` and the frontend `PositionManagement` types:

```
BREAK_EVEN | TRAILING_MOVE | PARTIAL_TP | TIME_EXIT
```

`action_executed` details:

* `BREAK_EVEN`  — `{ appliedAt?: ISO }`
* `TRAILING_MOVE` — `{ newStopPrice: number }` (REQUIRED)
* `PARTIAL_TP` — `{ levelId: string, executedPrice: number, closedVolume: number }` (ALL REQUIRED)
* `TIME_EXIT`  — `{ executedAt?: ISO }`

`action_failed` — `{ action, reason, retryable, levelId? }` (levelId when
action is `PARTIAL_TP`).

`plan_changed` carries the ENTIRE `PositionManagement` plan under `plan`,
including `paused` flips triggered by `position.management.pause/resume`
commands.
