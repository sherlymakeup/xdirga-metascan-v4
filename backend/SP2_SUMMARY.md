# SP2 — Append-only journal + EventBus

## Scope delivered

- SQLite journal (`WAL` + `synchronous=NORMAL`, busy_timeout default 5s)
- Tables: `events`, `commands`, `command_transitions` + append-only triggers
- Dedicated single-thread `ThreadPoolExecutor` owns write connection
- `Journal.append_event_committed` / `read_events` / `commit_bundle` / `try_insert_command_create`
- Writer TX paths (`append_event_committed`, `commit_bundle`, `try_insert_command_create`) use `try/except BaseException` + `rollback` before re-raise
- `commit_bundle`: command/transition requires envelope (SP2 atomicity; no transition-only rows)
- Removed misleading `get_or_create_command` (use `try_insert_command_create` / idempotent read)
- `EventBus`: `_publish_lock`, boot_id UUID4, sequence/revision, subscribe/unsubscribe
- COMMIT before fan-out; commit failure restores counters; no partial visibility
- Bounded subscriber queues; overflow → LAGGING + resync marker + warning log (enqueue after drain is hard fail if impossible)
- `close()` wakes waiters with `ClosedMarker` (`kind=bus_closed`) under publish lock before registry clear
- `ack_resync()` clears lagging; dropped events recovered via `read_events` only
- Command current row + transition share sequence with paired domain event
- Tests: crash, triggers, replay, order, concurrent, overflow, commit-before-publish, command TX, close-wake, try_insert rollback recovery

## Decisions

- stdlib `sqlite3` only (no aiosqlite)
- stdlib `logging` (not structlog) with explicit warning fields
- `run_in_executor(journal.executor, ...)` — never default executor for writes
- `append_event_committed` runs on writer thread against exclusive `_conn` (no nested submit deadlock)
- While `is_lagging`, further events dropped until `ack_resync` (no marker spam)
- `revision` increments only when `mutates_state=True`
- Transition-only rows without public events: forbidden
- SP1 wire models unchanged; bus overwrites `bootId`/`sequence`/`revision` only
- Config path `paths.journal_db` unused by SP2 unit tests (inject Path); wiring later
- Writer-connection pragma check: `synchronous` is connection-local; tests assert via `run_on_writer`

## Not in SP2

- FastAPI/SSE, MT5 gateway, RiskGate, snapshot rebuild
- Command lifecycle graph validation (RuntimeCore / SP3+)
- Frontend contract changes

## Crash-safety evidence

- Subprocess helper `tests/crash_helpers/interrupt_insert.py`: `BEGIN IMMEDIATE` + full valid event `INSERT`, then `os._exit(42)` — no rollback, no commit, no close, no finally (Windows-compatible hard terminate; SIGKILL unavailable)
- Parent test runs real disk DB: open schema → close → subprocess against path → nonzero exit 42 → optional `PRAGMA wal_checkpoint(TRUNCATE)` → `Journal` reopen → assert zero `crash-boot` rows (replay + raw COUNT) → subsequent `append_event_committed` succeeds on new boot
- In-process injects still cover raise-before-commit and monkeypatched disk-full rollback

## Verification

- Quality-blocker RED→GREEN: try_insert rollback recovery; commit_bundle envelope rule; close wakes waiter; resync enqueue invariant
- Focused SP2 suite: 29 passed
- Full `pytest tests/`: SP1 + SP2 green
- No commit (user override)
