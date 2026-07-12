# Runtime layer — architecture notes

This directory owns the frontend contract with the eventual **local XDirga
Runtime V4** backend. The UI never talks to a broker directly.

## Data sources

| `FrontendDataSource` | Meaning | Notes |
| --- | --- | --- |
| `DEVELOPMENT_FIXTURE` | In-memory fixtures | No runtime, no broker, no orders reach any external system. Fixture adapter is the reference implementation of `RuntimeAdapter`. |
| `LOCAL_RUNTIME`       | HTTP/SSE local runtime | Requires the local XDirga Runtime V4 to be running. `HttpRuntimeAdapter` is currently a **safe-fail** stub — reads return empty/disconnected views; commands reject with `NotImplementedError`. |

Broker environment (`TRIAL` | `LIVE`) and execution semantics (`LIVE`) are
separate dimensions from the frontend data source.

## Safety-fail contract for adapters

Read paths (`getSnapshot`, `getSnapshotEnvelope`, `getCapabilities`,
`getConnectionState`, `getHandshake`, `getDescriptor`) MUST NOT throw. If the
adapter has no data, it returns an **empty** shape — `createEmptySnapshot()`
for the CockpitSnapshot — with `DISCONNECTED` runtime state, empty lists,
`freshness: "UNAVAILABLE"`, and every capability `{ allowed: false }`.

Write / async paths (`connect`, `submitCommand`, `refresh*`) MUST reject with
`NotImplementedError` (or a real network error) — never silently succeed and
never fall back to fixture data.

## Prod guard

`<ProdFixtureGuard />` (mounted in `__root.tsx`) renders a persistent critical
banner when a production build is running against `DEVELOPMENT_FIXTURE`. This
catches deploy-time misconfiguration.

## Event pipeline (Phase 5C)

Adapter → `routeEvent` → `eventDeduplicator` → `eventHistoryStore` →
`notificationCenter`. Domain projection stores subscribe to the history store
and derive per-entity views (orders, positions, incidents, reconciliation runs).

## Snapshot hydration (Phase 5E.3)

`snapshotHydrationStore` subscribes to adapter snapshot envelopes and enforces
monotonic acceptance within a `bootId`. Rejections (`OLDER_REVISION`,
`OLDER_SEQUENCE`, `OBSOLETE_BOOT`, `DUPLICATE`) are recorded but never mutate
state. A new bootId resets the sequence window.

## Command orchestration (Phase 5D–5E)

All operator commands funnel through `submitCommand(...)` in
`commands/command-orchestrator.ts`. Pre-flight checks: role, capability,
handshake compatibility, connection state, freshness, execution-unknown locks,
reconciliation restrictions. Blocked results surface directly in the
confirmation dialog. State transitions are validated against
`command-transitions.ts` — invalid transitions are rejected and emit a
`system.validation.failed` event. Commands entering `EXECUTION_UNKNOWN`
auto-acquire an `ExecutionUnknownLock` on the target entity; locks are only
released by observed reconciliation events (`reconciliation.issue.resolved` /
`reconciliation.completed`).
