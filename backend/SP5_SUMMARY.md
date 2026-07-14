# SP5 — Locked Ruling Coverage

Status: Round 8 final verifier lifecycle cleanup implemented; verification evidence below.

## Coverage: R1–R27

| Ruling | Exact locked scope | Evidence |
|---|---|---|
| R1 | Exact eight-gate order; reducing commands bypass entry-only gates; pending intent then send/outcome | `risk_gate.GATE_NAMES`; gate trace and multi-breach tests |
| R2 | No blind retry; shielded timeout; verification-only reads; exhausted verification fails CRITICAL with retained lock; temporal polling with >=2 polls + history | pipeline uncertainty tests; real gateway temporal verification tests |
| R3 | MT5 mutation only in gateway; gateway-thread identity; serialized ingress; temporal verify via submit_command same queue | seam static/runtime/ingress tests; SP3 lineage comment retained |
| R4 | `mutationInFlight` excluded from staleness SLO | health and delayed-send tests |
| R5 | Floor to step; below broker minimum uses `RISK_BUDGET_BELOW_MIN_VOLUME`; never round up | Decimal sizing tests; A7 dedicated tests |
| R6 | Internal canonical `request_json`, atomic with `command.created`, absent from REST | persistence/idempotency tests |
| R7 | Global idempotency replay/conflict semantics | transport/internal persistence tests |
| R8 | Transport/internal XOR DB records with shared indexed identity | journal constraint and internal persistence tests |
| R9 | No auth material persisted | transport security tests |
| R10 | Internal entry uses the same pipeline; no invented wire kind; transport cannot increase exposure | internal ingress and 422 tests |
| R11 | Exact entry fields; no volume; reserved price; liquidation-quote SL/TP validation; risk max and whitelist fail closed | contract/risk-gate tests |
| R12 | Locked defaults, startup validation, units, `CALIBRATE-SP6` broker comment | config/default/comment tests |
| R13 | Exact Decimal loss sizing with fresh facts, fail-closed metadata, fixed fixtures, risk invariant | risk sizing/property/fake metadata tests |
| R14 | `INTERNAL_ENTRY_MARKET` internal identity; enum-pure transport status; internal GET byte-identical 404 | persistence and transport-isolation tests |
| R15 | Symbol intent persists before send; successful send without confirmed position remains `EXECUTION_UNKNOWN`; order/deal persist before verification; position persists and identity upgrades before terminal cleanup | `test_sp5_r5_entry_unknown.py`; durable entry intent tests |
| R16 | Restart rehydrates persisted symbol/order/deal/position correlation, persists explicit `EXECUTION_UNKNOWN`, emits reconciliation detection, then schedules production verification; unresolved recovery retains durable state and alerts | `test_sp5_r5_recovery_rehydration.py` |
| R17 | Determinate success releases locks; ambiguity retains lock; negative verification waits for the full monotonic budget and configured poll interval | `test_sp5_r5_temporal_verdict.py`; `test_sp5_r5_temporal_interval.py`; exhausted-budget tests |
| R18 | Full close rereads volume; partial floor/min/dust rules; cancel mapping | gateway mutation tests |
| R19 | Protection update preserves omitted broker field atomically | bidirectional protection tests |
| R20 | Bulk/emergency bot-only children, continue-on-error, deterministic summary, UNKNOWN handling and CRITICAL failures | bulk/emergency integration tests |
| R21 | Emergency halt-before-I/O, cancel, close with `KILL_SWITCH`, one rescan, persistent halt | emergency ordering/mid-sweep tests |
| R22 | Request hygiene: magic, deviation, filling mode, broker-safe command correlation comment | exact request mapping tests |
| R23 | SP5 close reason whitelist is only `MANUAL`/`KILL_SWITCH`; runtime `ValueError` fence; catalog/camelCase only | close correlation and whitelist tests |
| R24 | Broker SL/TP attribution remains SP7 carry-forward | CONTRACT-NOTE below |
| R25 | Contract-first cited tests; obsolete behavior removed; SP1–SP4 and schema contract retained | full regression suite |
| R26 | Required RCA, emergency composition, one-entry note, Phase-2 note, SP7 notes included below | this document |
| R27 | One append-only implementation checkpoint after full green | pending final commit only |

## Coverage: A1–A7

| Addendum | Exact locked scope | Evidence |
|---|---|---|
| A1 | R1–R27 delivered atomically; no partial acceptance | one correction tree/checkpoint |
| A2 | Internal event `payload.kind="INTERNAL_ENTRY_MARKET"`; raw internal fields do not leak | event and REST tests |
| A3 | Internal command ID and random ID produce byte-identical 404 | transport-isolation test |
| A4 | Fresh gateway-thread `orders_get` at sweep/rescan; foreign pending observed untouched | bulk/emergency fake tests |
| A5 | Decimal at boundaries; positive floor arithmetic; one gateway float conversion | sizing and request tests |
| A6 | SP3 no-send test superseded by cited SP5 seam invariant | gateway lineage comment and seam tests |
| A7 | Cause-specific gate 6/7 reason map with deterministic multi-breach precedence | dedicated A7 reason tests (`test_sp5_a7_gate_reasons.py`) |

## A7 reason map

- Nonpositive `riskFraction`: `VALIDATION_FAILED` at validation.
- Above configured maximum: `RISK_FRACTION_EXCEEDS_MAX`.
- Position/total/symbol exposure ceiling: `ENTRY_EXPOSURE_LIMIT`.
- Daily loss breach: `DAILY_LOSS_LIMIT_REACHED`.
- Arithmetic or sizing metadata failure: `SIZING_METADATA_INVALID`.
- Floored volume below broker minimum: `RISK_BUDGET_BELOW_MIN_VOLUME`.
- Computed volume above broker maximum: `VOLUME_ABOVE_BROKER_MAX`.

Precedence: `VALIDATION_FAILED` → `RISK_FRACTION_EXCEEDS_MAX` → `ENTRY_EXPOSURE_LIMIT`/`DAILY_LOSS_LIMIT_REACHED` → `SIZING_METADATA_INVALID` → `RISK_BUDGET_BELOW_MIN_VOLUME` → `VOLUME_ABOVE_BROKER_MAX`. Volume excluded from positive-finite check so floor-to-zero hits `RISK_BUDGET_BELOW_MIN_VOLUME`.

## Round 4 changes

### Production code

| File | Change |
|---|---|
| `src/metascan/pipeline/risk_gate.py` | Removed `volume` from positive-finite check so floor-to-zero yields `RISK_BUDGET_BELOW_MIN_VOLUME` instead of `SIZING_METADATA_INVALID` |
| `src/metascan/pipeline/command_pipeline.py` | Async temporal verification loop; durable intent persistence before send; order/deal/position updates; restart recovery task; registry ticket upgrade; terminal journal/registry/symbol-lock cleanup |
| `src/metascan/pipeline/risk_config.py` | Validated temporal verification poll interval configuration |

### New test files

| File | Tests | Covers |
|---|---|---|
| `tests/test_sp5_temporal_verification_budget.py` | 8 | Default 10s budget; real pipeline delayed convergence for close/partial/modify/entry; exhausted-budget lock retention |
| `tests/test_sp5_durable_entry_intent.py` | 4 | Journal persistence before send; clear on terminal; restart restore; kill/restart integration |
| `tests/test_sp5_entry_resolution_cleanup.py` | 4 | Ticket upgrade on success; terminal clears lock for new entry; stale lock retention; duplicate lock rejection |
| `tests/test_sp5_a7_gate_reasons.py` | 8 | `RISK_BUDGET_BELOW_MIN_VOLUME`; `VOLUME_ABOVE_BROKER_MAX`; multi-breach precedence (risk fraction > exposure > daily loss > metadata > below min > above max); forex/XAU calibration fixtures |

### Test mapping for changed behavior

| Behavior | Before | After |
|---|---|---|
| Volume floor-to-zero reason | `SIZING_METADATA_INVALID` (bug) | `RISK_BUDGET_BELOW_MIN_VOLUME` (correct) |
| Entry intent journal persistence | In-memory only | Journal before send, cleared on terminal |
| Entry intent restart recovery | Manual DB insertion in test | Production lifecycle through `_recover_entry_intents` |
| Terminal entry cleanup | Lock + pending only | Lock + pending + journal intent cleared |
| Verify temporal proof | Fabricated dicts | Real FakeMt5 + Mt5Gateway call_log assertions |

## Round 5 blocker mapping

| Blocker | Production change | Exact tests |
|---|---|---|
| R15 successful-entry lifecycle | `command_pipeline.py` persists order/deal, routes accepted entries without confirmed position through `EXECUTION_UNKNOWN`, retains lock/intent during ambiguity, persists position and upgrades identity before cleanup | `test_sp5_r5_entry_unknown.py` |
| R16 restart recovery | `command_pipeline.py` rehydrates persisted broker correlation, persists `EXECUTION_UNKNOWN`, emits reconciliation detection, runs production verifier, retains durable state and alerts when unresolved | `test_sp5_r5_recovery_rehydration.py` |
| Broker correlation after restart | `gateway.py` consumes persisted request order/deal/position/symbol correlation when in-memory verification context is absent | `test_sp5_r5_recovery_rehydration.py` |
| R12 temporal startup validation | `risk_config.py` rejects nonpositive timeout/interval and interval greater than timeout | `test_sp5_r5_risk_config_validation.py` |
| Full verification budget | `command_pipeline.py` uses a monotonic deadline, configured temporal spacing, immediate positive resolution, and defers negative terminalization until deadline | `test_sp5_r5_temporal_verdict.py`; `test_sp5_r5_temporal_interval.py` |

## Round 6 temporal verifier race

Root cause: `_temporal_verify()` used `verify_poll_interval_ms` both as poll cadence and as the maximum wait for each gateway verification future. Equal-cadence calls timed out while still running, their results were discarded, and replacement calls accumulated on the serialized gateway queue.

Production fix: `command_pipeline.py` now uses one monotonic overall deadline, anchors each next poll start to the previous poll start, keeps at most one verification future active, waits for that future using the remaining overall budget, consumes boundary-completed results before timeout resolution, and never submits a replacement while a prior call remains active. `fake_mt5.py` adds recurring call-delay control for deterministic production-path race tests.

| Requirement | Exact test |
|---|---|
| Equal 50 ms cadence race | `test_sp5_r6_temporal_verifier_race.py::test_a_equal_cadence_50ms_delay_converges` |
| Slow call exceeds poll interval | `test_sp5_r6_temporal_verifier_race.py::test_b_duration_exceeds_interval_still_converges` |
| Maximum one in-flight verification | `test_sp5_r6_temporal_verifier_race.py::test_c_max_one_in_flight_no_buildup` |
| Verification-call start cadence | `test_sp5_r6_temporal_verifier_race.py::test_d_call_start_spacing_honors_interval` |
| Near-deadline result precedence | `test_sp5_r6_temporal_verifier_race.py::test_e_near_deadline_completion_consumed` |
| Existing delayed/recovery matrix | `test_sp5_temporal_verification_budget.py`; `test_sp5_r5_temporal_verdict.py`; `test_sp5_r5_recovery_rehydration.py`; `test_sp5_durable_entry_intent.py` |

Stability suite results: run 1 `26 passed`; run 2 `26 passed`; run 3 `26 passed`; run 4 `26 passed`; run 5 `26 passed`.

## Round 7 final verifier state machine

Round 6 residual root cause: completed verification futures that raised were consumed as `None` but remained active. The loop repeatedly awaited the same failed future, prevented retries, and could spin until deadline.

Final behavior: the verifier explicitly separates idle, pending, successful completion, and exceptional completion. Async and synchronous transient failures are consumed, logged, cleared, then retried at monotonic cadence while budget remains. One source future remains active at most; slow calls use remaining overall budget; boundary-completed results are inspected before timeout fallback; cancellation propagates and installs safe source/wrapper exception drains without retry.

| Production behavior | Exact tests |
|---|---|
| One async exception then convergence | `test_sp5_r7_temporal_verifier_exceptions.py::test_a_completed_exception_is_consumed_once_then_success_retries_at_cadence` |
| Multiple exceptions, heartbeat responsiveness, one in-flight | `test_sp5_r7_temporal_verifier_exceptions.py::test_b_multiple_async_exceptions_then_success_without_spin` |
| Exceptions through full budget without call storm | `test_sp5_r7_temporal_verifier_exceptions.py::test_c_async_exceptions_until_deadline_use_full_budget_without_call_storm` |
| Synchronous submission failure and implementation `TypeError` retry | `test_sp5_r7_temporal_verifier_exceptions.py::test_d_synchronous_verify_submission_failure_retries_at_cadence`; `test_d_type_error_from_modern_verify_is_one_submission_then_cadence_retry` |
| Boundary-completed result precedence | `test_sp5_r7_temporal_verifier_exceptions.py::test_e_same_turn_completed_result_is_inspected_before_timeout` |
| Pending-timeout exception lifecycle | `test_sp5_r7_temporal_verifier_exceptions.py::test_e_pending_timeout_drains_late_source_and_wrapper_exception` |
| Cancellation propagation and exception drain | `test_sp5_r7_temporal_verifier_exceptions.py::test_f_cancellation_propagates_without_retry_and_production_drains_exception` |
| Durable ambiguity lock and alert | `test_sp5_r7_temporal_verifier_exceptions.py::test_g_exception_ambiguity_retains_lock_and_emits_alert_on_hot_path` |

Round 7 stability: runs 1–10 each `11 passed`. Combined temporal/recovery stability: runs 1–10 each `37 passed`.

## Round 8 verifier lifecycle cleanup

Round 7 boundary root cause: when source completion and `wait_for` timeout shared a scheduler boundary, the source exception could be consumed while the wrapped or shield future retained the same exception. Pending sources completing after logical timeout had the same ownership gap.

Cleanup design: each attempt has explicit ownership. `wrap_future` consumes the source completion, `shield` consumes the wrapped completion, and verifier retirement consumes or schedules a drain for the terminal waiting future. Cancelled shield boundaries inspect the completed wrapper; pending wrapperless sources remain single-flight and are drained on timeout or cancellation. Cleanup never awaits beyond the monotonic budget and never submits after deadline.

| Production behavior | Exact tests |
|---|---|
| Same-turn boundary exception drains source, wrapper, shield | `test_sp5_r8_temporal_verifier_retirement.py::test_same_turn_source_exception_and_timeout_retires_every_future` |
| Pending deadline then late exception | `test_sp5_r8_temporal_verifier_retirement.py::test_pending_at_deadline_returns_and_late_exception_retires_every_future` |
| Cancelled shield boundary success/error | Round 8 cancelled-waiting boundary tests |
| Source `TimeoutError` before deadline retries | Round 8 source-timeout retry test |
| Wrapper construction failure: pending, success, error, cancellation | Round 8 wrapper-failure lifecycle tests |

Round 8 stability: runs 1–10 each `9 passed`. Round 7 stability: runs 1–10 each `11 passed`. Combined temporal/recovery stability: runs 1–10 each `46 passed`. SP6 was not started.

## RCA and mechanical prevention

The approved design was previously summarized instead of traced mechanically through production boundaries. Tests injected verdict dictionaries that the real gateway could not produce, and direct gate tests missed the internal pipeline dataclass transition crash. Prevention now requires pipeline-level rejection tests, arbiter tests fed by the real gateway fact producer, a pytest collection hook rejecting empty/assertion-free SP5 modules, exact locked numbering here, and full-suite verification before the single checkpoint.

## Emergency composition

`runtime.emergencyKill` persists halt before broker I/O, rejects new entries immediately, cancels fresh bot-magic pending orders, closes fresh bot-magic positions with `KILL_SWITCH`, continues per child, rescans once for stragglers, emits one parent terminal transition, and remains halted until explicit start/resume.

## One entry per symbol

Entry lock scope is `entry:<brokerSymbol>`. Exactly one unresolved entry per broker symbol may exist. Magic remains ownership authority; intent supplies correlation only.

## Phase-2 contract note

Exposing strategy-originated orders through the command-status API requires a frontend command-kind enum addition. SP5 keeps transport enums pure and internal identity in persisted origin/execution columns plus passthrough-legal event payload values.

## CONTRACT-NOTE: SP7

SP7 owns deal-history reconciliation, durable resolution of locks retained after exhausted verification, bot-magic position anomaly adjudication, and correction of broker-side SL/TP closes that SP3 can initially classify as `MANUAL`.

## Verification

- Full suite: `403 passed, 1 existing Starlette/httpx deprecation warning`.
- Round 8 tests: `9 passed`; 10 consecutive runs each `9 passed`.
- Round 7 repeat: 10 consecutive runs each `11 passed`.
- Combined Round 5–8 temporal/recovery stability: 10 consecutive runs each `46 passed`.
- Round 7 tests: `11 passed`; 10 consecutive runs each `11 passed`.
- Combined temporal/recovery stability: 10 consecutive runs each `37 passed`.
- Delayed-convergence matrix: `24 passed`.
- Round 5 targeted blocker suite: `21 passed`.
- Schema hash suite: `5 passed`.
- Compile check: `uv run python -m compileall -q src tests` passed.
- Diff check: `git diff --check` passed.
- Temporal verification uses monotonic full-budget deadlines and configured poll spacing; delayed convergence after 30% of the window resolves `COMPLETED`.
- Successful entry without visible position persists order/deal and remains `EXECUTION_UNKNOWN`; duplicate symbol entry is rejected while lock and intent remain durable.
- Position discovery persists `position_ticket`, upgrades symbol identity to ticket, then completes and cleans durable state.
- Restart recovery persists explicit `EXECUTION_UNKNOWN`, emits reconciliation detection, rehydrates persisted broker tickets into production verification, and either resolves or retains intent/lock with a CRITICAL alert.
- A7 gate reasons remain covered: exact `RISK_BUDGET_BELOW_MIN_VOLUME` and `VOLUME_ABOVE_BROKER_MAX` with deterministic multi-breach precedence.
