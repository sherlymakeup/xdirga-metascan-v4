# SP5 — Locked Ruling Coverage

Status: Round 4 blockers implemented, full suite green.

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
| R15 | Symbol entry intent before send; one symbol lock; magic ownership; result order/deal capture and position correlation; journal persist before send, update tickets on mutation result and verification, clear on terminal | gateway context and entry verification tests; durable entry intent journal tests |
| R16 | Entry intents persisted and recovered into uncertainty verification; restart creates async recovery task with temporal verify; drives delayed broker convergence to terminal resolution; no manual DB insertion | restart recovery tests through production lifecycle |
| R17 | Locks release on all determinate rejections; uncertainty retains lock; temporal verify accepts False only after >=3 polls and elapsed >30% budget | pipeline-level gate rejection, uncertainty tests, exhausted budget retention tests |
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

- Full suite: `357 passed, 1 existing Starlette/httpx deprecation warning`.
- Round 4 new tests: `24 passed`.
- Real gateway temporal verification: temporal poll loop with >=2 polls + >=1 history_deals_get per verify call; call timestamps recorded; False accepted only after >=3 polls and elapsed >30% of verification budget.
- Delayed broker convergence: mutation timeout → temporal verify loop → broker state changes → exact COMPLETED with lock released; tested for close, partial, modify, entry.
- Exhausted budget: deadline reached → FAILED with lock retained; CRITICAL alert emitted.
- Durable entry intent: journal `entry_intents` table persistence before mutation send; order/deal/position ticket updates on mutation result and verification; cleared on terminal.
- Restart recovery: killed first pipeline → second recovers entry intent from journal, loads InternalCommandRecord from commands DB, creates async recovery task that drives temporal verification → delayed position → COMPLETED with journal/registry/lock cleared.
- A7 gate reasons: exact `RISK_BUDGET_BELOW_MIN_VOLUME` and `VOLUME_ABOVE_BROKER_MAX` with deterministic multi-breach precedence.
