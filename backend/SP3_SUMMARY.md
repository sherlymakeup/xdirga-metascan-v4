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
- GatewayMetrics thread-safety with `threading.Lock`
- Consumer heartbeat tracking with automatic state transition to `DISCONNECTED` with `HARD_FAIL` on timeout
- Soft error vs Hard fail streak distinguishing logic ensuring transient failures only map to `DEGRADED`
- No order execution; no account.updated/tick.updated
- Documented assumption regarding session calendars and tick budgeting

## Decisions

- positionId = str(ticket)
- exitReason = MANUAL only (never MANUAL_CLOSE)
- External partial = position.partially_closed
- External SL/TP = position.protection_changed
- Transient open/close blind spot accepted (SP7 later)
- MappingProxyType for frozen maps (no frozendict dep)
- Metric synchronization overhead is bounded by small lock scopes on collection and percentile extraction
- Tasks cancellation (`stop`) correctly awaits target to eliminate `CancelledError` warnings in logs

## Not in SP3

- order_send / RiskGate / FastAPI SSE / SP7 history / RuntimeCore rebuild
