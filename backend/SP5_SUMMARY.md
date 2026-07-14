# SP5 — Command Pipeline Correction Summary

Status: correction implemented; verification evidence recorded below.

## Locked requirements

| Requirement | Delivered |
|---|---|
| R1 | One asyncio command pipeline handles transport and internal ingress. |
| R2 | Persisted command identity distinguishes `TRANSPORT` and `INTERNAL`. |
| R3 | Canonical request fingerprint enforces replay/conflict idempotency. |
| R4 | Durable command lifecycle and transition/event sequence invariant. |
| R5 | Exact ordered eight-gate trace with first-failure short circuit. |
| R6 | Entry-only gates do not block reduce, protection, cancel, control, or emergency actions. |
| R7 | Decimal-only downward risk sizing; invalid inputs fail closed. |
| R8 | Injected MT5 gateway thread owns broker reads, checks, sends, and verification. |
| R9 | Every mutation uses `order_check`; explicit rejection never sends. |
| R10 | Pending close, partial, modify, and entry intents retain reconciliation identity. |
| R11 | Ambiguous execution transitions directly to `EXECUTION_UNKNOWN`; never resends. |
| R12 | Per-kind verification proves execution or nonexecution from broker facts. |
| R13 | Emergency halt persists before I/O, then cancels orders, closes positions, rescans. |
| R14 | Bulk children have unique command IDs, continue independently, and aggregate exact outcomes. |
| R15 | Bot full closes emit correlated `position.closed` and `trade.closed`. |
| R16 | SP5 full-close exit reasons are only `MANUAL` and `KILL_SWITCH`. |
| R17 | Active or unresolved mutation scopes expose `mutationInFlight`. |
| R18 | Partial close normalizes downward and rejects below-minimum or dust remainder. |
| R19 | Gate evaluation consumes one immutable runtime-facts snapshot. |
| R20 | `InternalEntryRequest` structurally excludes volume and rejects pending entry price. |
| R21 | Pending-order observation includes ticket, symbol, magic, volume, and type. |
| R22 | Unsupported registered commands fail canonically; unknown wire kinds return 422. |
| R23 | `SUBMITTING` is durable without an SSE transition event. |
| R24 | Await timeout shields the broker future and preserves uncertainty. |
| R25 | Emitted command reasons stay within the canonical SP5 reason table. |
| R26 | Explicit positive nonzero `bot_magic` is mandatory; foreign magic is never mutated. |
| R27 | Test phases match SP5 ownership; empty test modules are rejected. |

## Correction addenda

- C1/C4: close, partial-close, protection, cancel, and entry verification use kind-specific facts. Close succeeds only when the target position is absent.
- C2: intent-matched bot closes emit both close events with command/correlation metadata. Exit-reason emission is whitelisted.
- C3: one command crash becomes a canonical failed command plus CRITICAL alert without killing the consumer; infrastructure failure marks the pipeline unhealthy.
- H1: bulk and emergency operations preserve per-child outcomes, foreign counts, ordering, rescans, stragglers, and parent terminality.
- H3: emitted command reasons are canonical. Unresolved verification remains `EXECUTION_UNKNOWN` with `OUTCOME_AMBIGUOUS`, CRITICAL alert, retained lock, and no resend.
- H4: broker comments retain `CALIBRATE-SP6` and are limited to 31 characters.
- H5: entry execution/sizing uses BUY ask or SELL bid; stop-loss validity uses BUY bid or SELL ask.
- H6: `CommandPipeline` requires a positive nonzero `bot_magic`.
- P1: collection includes an AST guard rejecting empty `test_*.py` modules.
- P2: correction tests are named for SP5 ownership.
- P3: touched SP4 assertions document the SP5 lifecycle changes they accept.

## Safety invariants

- Direct uncertainty: `EXECUTION_UNKNOWN`; never resend.
- Verification timeout: retain uncertainty, intent, and mutation lock; emit CRITICAL alert.
- Bot ownership: only exact configured nonzero magic is mutable.
- Emergency order: persist halt, cancel bot orders, close bot positions, rescan.
- Frontend `src/` remains untouched.

## Verification

- Focused constructor/emergency regression: `46 passed`.
- H4/H5 focused regression: `28 passed`.
- Canonicality/resilience regression: `48 passed`.
- Full suite after corrections, phase renames, and empty-module guard: `326 passed, 1 warning`.
- Warning: existing Starlette `httpx` deprecation in `tests/test_web/test_api_lifecycle.py`.

## Changed scope

- Pipeline, risk gate, MT5 gateway/consumer/mapping, pending-intent seams.
- SP5 behavioral, verification, bulk/emergency, close-correlation, resilience, mutation, and structural tests.
- Web fixtures/assertions only where SP5 constructor/lifecycle wiring requires it.
