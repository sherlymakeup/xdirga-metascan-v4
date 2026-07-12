# SP2 — Journal + EventBus Design

Status: locked requirements for implementation. No frontend contract deviation. SP1 contract models (`RuntimeEventEnvelope`, command types) are inputs; this slice owns durable append + in-process fan-out only.

## 1. Goal

Crash-safe append-only event journal and command store on SQLite, plus an asyncio EventBus that:

- assigns authoritative total order (`sequence`) per `bootId`
- persists before any subscriber observes an event
- never blocks the publisher on slow subscribers
- supports exact, boot-scoped replay for resync

Out of scope: FastAPI/SSE, MT5 gateway, RiskGate, snapshot rebuild, frontend wire changes.

## 2. Durability model (accepted)

| Setting | Value | Rationale |
|---|---|---|
| `journal_mode` | `WAL` | concurrent readers; writers do not block snapshot/replay |
| `synchronous` | `NORMAL` | accepted durability: after `COMMIT` returns, row is durable for process crash / clean OS crash on this host; power-loss edge cases accepted |
| Foreign keys | `ON` | integrity on command FK-like refs if used |
| Busy timeout | configurable, default 5s | fail loud under lock contention rather than hang forever |

Non-goals for this slice: multi-writer throughput, async DB drivers, writer-queue architectures. Alternatives considered and **rejected**: dedicated asyncio writer queue in front of SQLite; pure in-memory bus with periodic flush; `aiosqlite` as the sole writer path (see §11).

## 3. Schema

Single SQLite file (path from config; gitignored `*.sqlite`).

### 3.1 `events` (immutable journal)

Canonical store of full event envelopes as JSON. Indexed columns exist for query/replay only; payload truth is `envelope_json`.

```sql
CREATE TABLE events (
  boot_id       TEXT    NOT NULL,
  sequence      INTEGER NOT NULL,
  type          TEXT    NOT NULL,
  entity_id     TEXT    NULL,          -- nullable; position/order/command/etc. when applicable
  ts            TEXT    NOT NULL,      -- ISO-8601 from envelope (informational)
  envelope_json TEXT    NOT NULL,      -- full RuntimeEventEnvelope wire JSON
  PRIMARY KEY (boot_id, sequence)
);

CREATE INDEX idx_events_boot_seq   ON events (boot_id, sequence);
CREATE INDEX idx_events_boot_type  ON events (boot_id, type);
CREATE INDEX idx_events_entity     ON events (boot_id, entity_id)
  WHERE entity_id IS NOT NULL;
```

Immutability via triggers (reject any mutation):

```sql
CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: DELETE forbidden');
END;
```

No `UPDATE`. No soft-delete. Vacuum/export is ops, not runtime.

### 3.2 Commands: current record + append-only transitions

Two tables: mutable **current** projection for poll/idempotency; immutable **transition log**.

```sql
CREATE TABLE commands (
  command_id         TEXT PRIMARY KEY,
  idempotency_key    TEXT NOT NULL UNIQUE,
  client_request_id  TEXT NOT NULL,
  correlation_id     TEXT NOT NULL,
  kind               TEXT NOT NULL,
  target_id          TEXT NULL,
  state              TEXT NOT NULL,
  progress           REAL NULL,
  current_step       TEXT NULL,
  message            TEXT NULL,
  error_code         TEXT NULL,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  record_json        TEXT NOT NULL   -- full RuntimeCommandStatus wire JSON
);

CREATE TABLE command_transitions (
  boot_id        TEXT    NOT NULL,
  sequence       INTEGER NOT NULL,   -- same EventBus sequence space as events when transition is journaled with an event; else own monotonic per-boot transition seq if transition-only (see §7)
  command_id     TEXT    NOT NULL,
  from_state     TEXT    NULL,       -- NULL on create
  to_state       TEXT    NOT NULL,
  ts             TEXT    NOT NULL,
  transition_json TEXT   NOT NULL,  -- full transition record JSON
  PRIMARY KEY (boot_id, sequence, command_id)
);

CREATE INDEX idx_cmd_transitions_cmd ON command_transitions (command_id, boot_id, sequence);

CREATE TRIGGER command_transitions_no_update
BEFORE UPDATE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: UPDATE forbidden');
END;

CREATE TRIGGER command_transitions_no_delete
BEFORE DELETE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: DELETE forbidden');
END;
```

**Boundary:** `commands` may `UPDATE` only through the command store API that also appends a `command_transitions` row in the **same SQLite transaction** as any related domain event (when the transition is event-backed). Illegal lifecycle jumps are rejected in application code using the same transition graph as frontend `command-transitions` (SP3+ wiring); SP2 stores what RuntimeCore validates.

## 4. Counters: sequence and revision

Per process boot:

| Counter | Scope | Start | Increments when |
|---|---|---|---|
| `boot_id` | process lifetime | new UUID4 at EventBus/Journal open | never (new boot = new id) |
| `sequence` | per `boot_id`, all event types | `0` baseline; first published event is `1` | every successfully journaled + published event |
| `revision` | per `boot_id` | `0` baseline | only **state-mutating** events |

Rules:

- Clean baseline each new `boot_id`: in-memory counters reset; DB retains prior boots for history/replay of old boots if needed.
- `sequence` is the **total order** across all types for that boot. Type does not get its own sequence.
- `timestamp` / `occurred_at` / `emitted_at` are informational only; never used for ordering.
- State-mutating vs non-mutating classification is owned by RuntimeCore (caller supplies `mutates_state: bool` or equivalent). EventBus increments `revision` only when that flag is true, **inside** the publish lock after sequence allocation.
- Envelope fields written by EventBus before journal: `bootId`, `sequence`, `revision` (caller supplies the rest of the envelope, including `eventId`, `type`, payload, timestamps).

## 5. EventBus (asyncio)

### 5.1 Components

- One process-wide `EventBus` instance.
- Single `asyncio.Lock` named `_publish_lock`.
- In-memory: `sequence`, `revision`, `boot_id`, subscriber registry, lagging count.
- Journal writer: **one dedicated executor thread** (stdlib `concurrent.futures.ThreadPoolExecutor(max_workers=1)` or equivalent), exclusive owner of SQLite write connections for journal append.

### 5.2 Publish critical section (exact)

`async def publish(envelope_partial) -> RuntimeEventEnvelope`:

While holding `_publish_lock` (and only there):

1. **Allocate counters**  
   - `sequence += 1`  
   - if state-mutating: `revision += 1`  
   - stamp envelope: `boot_id`, `sequence`, `revision`

2. **Journal append + await COMMIT**  
   - Serialize full envelope to canonical wire JSON (contract `WireModel` / camelCase).  
   - `await loop.run_in_executor(journal_executor, journal.append_event_committed, row)`  
   - `append_event_committed` opens a write transaction, `INSERT`, `COMMIT`, returns only after COMMIT succeeds.  
   - On failure: **do not** fan-out; leave counters as allocated only if the row is proven committed; if COMMIT failed, roll back counter allocation (restore previous sequence/revision) and raise. No partial visibility.

3. **Fan-out inside the same lock**  
   - For each active subscriber: `queue.put_nowait(envelope)` (or overflow path §5.3).  
   - Publisher never `await queue.put` and never blocks on a full subscriber.

4. Release lock. Return the stamped envelope.

Authoritative total order for a `bootId` is the order of **successful lock acquisition + counter allocation** for publishes that complete COMMIT. Concurrent publishers serialize on `_publish_lock`.

### 5.3 Subscribers

- Each subscriber: bounded `asyncio.Queue(maxsize=N)` (config; default e.g. 1024).
- Overflow path (atomic under `_publish_lock` for that subscriber):
  1. Mark subscriber state `LAGGING = True` (explicit flag).
  2. Clear the queue completely.
  3. Enqueue a single **resync marker** (internal control message, not a journaled domain event): `{ "kind": "resync_required", "boot_id", "last_committed_sequence", "reason": "subscriber_overflow" }`.
  4. Emit warning log with **subscriber id**.
  5. Increment/maintain process-wide lagging subscriber count; expose via `lagging_subscriber_count` property / health helper.
- Subscriber leaves `LAGGING` only after it successfully consumes the resync marker and completes its own resync protocol (snapshot + `read_events`); bus does not auto-clear without subscriber acknowledgement API (`subscriber.ack_resync()`).
- Dropped mid-queue events are not re-delivered via live fan-out; recovery is replay only.

Publisher isolation: a stuck or slow consumer cannot stall other subscribers or the publish path beyond the lock-held `put_nowait` / overflow work (O(subscribers), no I/O).

### 5.4 Subscribe / unsubscribe API

```text
sub = await bus.subscribe(subscriber_id: str, maxsize: int | None = None) -> Subscription
# Subscription: async iterator / queue.get(); .id; .is_lagging; .ack_resync()
await bus.unsubscribe(subscriber_id)
bus.lagging_subscriber_count -> int
bus.boot_id / bus.sequence / bus.revision  # read-only snapshots
```

## 6. Replay API (exact)

```python
def read_events(
    boot_id: str,
    after_sequence: int,
    limit: int,
) -> list[RuntimeEventEnvelope]:
```

Semantics:

| Rule | Behavior |
|---|---|
| Boot-scoped | only rows with `boot_id = :boot_id` |
| After-exclusive | `sequence > after_sequence` |
| Order | `ORDER BY sequence ASC` |
| Bound | `LIMIT :limit` (`limit >= 1`; hard cap e.g. 10_000) |
| Empty | `[]` if none; never invent gaps |

Used by: boot rebuild helpers, SSE catch-up (later), tests. Live subscribers that lag must call this after snapshot, not rely on cleared queue contents.

Consumers (bus subscribers, SSE adapters, tests) **always** sort/resume by `sequence` within a `bootId`; never by timestamp.

## 7. Command journaling boundaries

| Operation | Persist | EventBus |
|---|---|---|
| Create command (idempotent insert) | `INSERT commands` + `INSERT command_transitions` (from NULL → initial state) | emit `command.created` (or contract equivalent) via publish after same TX when event is required |
| Valid state transition | `UPDATE commands` + `INSERT command_transitions` | emit matching `command.*` event via publish |
| Idempotent replay (same key) | read-only `commands` | no new event, no new transition |
| Rejected illegal transition | no `commands` mutation | optional reject event only if RuntimeCore defines one; SP2 does not invent types |

When a domain event and command row must stay consistent: **one SQLite transaction** performed inside the journal executor call invoked from the publish path (or a `journal.commit_bundle(events=[], command_ops=[])` used only under `_publish_lock` before fan-out). Fan-out still only after COMMIT.

Command transition sequences: prefer tying transitions to the **same** `sequence` as the published command event. Transition-only rows without a public event are forbidden in SP2 to avoid dual sequence spaces.

## 8. Lifecycle and shutdown

1. **Open:** create schema if missing; set WAL + synchronous=NORMAL; load nothing into sequence/revision from old boots; mint new `boot_id`; counters at 0.
2. **Run:** all publishes through EventBus; all command writes through journal APIs.
3. **Shutdown (graceful):**
   - stop accepting new publishes (flag / close)
   - wait for in-flight publish (lock holders) to finish COMMIT + fan-out
   - under `_publish_lock`, drain each subscriber queue and `put_nowait` a terminal
     control marker `{ "kind": "bus_closed", "subscriber_id", "boot_id" }` (`ClosedMarker`)
     so blocked `Subscription.get()` waiters unblock deterministically; then clear registry
   - close SQLite connections on the journal thread; shutdown executor
   - do not DELETE journal rows
4. **Crash:** in-flight uncommitted INSERT is rolled back by SQLite → no partial row; next boot new `boot_id`; old boot history remains queryable via `read_events(old_boot_id, ...)`.

## 9. Error handling

| Failure | Behavior |
|---|---|
| SQLite COMMIT error during publish | restore sequence/revision; raise to caller; no fan-out |
| Trigger abort on UPDATE/DELETE | propagate; treat as programming error |
| Subscriber queue full | overflow path §5.3; publish continues |
| Duplicate `idempotency_key` insert | return existing command record; no second transition |
| `read_events` unknown boot | `[]` |
| `limit` out of range | raise `ValueError` |
| Double-open journal writer | refuse; single writer connection/thread |
| Publish after shutdown | raise `EventBusClosed` |

Logging: structlog; overflow warnings include `subscriber_id`, `boot_id`, `sequence`, queue maxsize.

## 10. File map (implementation target)

```text
backend/src/metascan/journal/
  __init__.py
  schema.sql          # DDL + triggers
  db.py               # connect, pragmas, schema apply
  events.py           # append_event_committed, read_events
  commands.py         # upsert current + append transition (same TX helpers)
backend/src/metascan/bus/
  __init__.py
  event_bus.py        # EventBus, Subscription, publish lock, fan-out, lagging
backend/tests/
  test_journal_crash.py
  test_journal_triggers.py
  test_event_bus_order.py
  test_event_bus_overflow.py
  test_replay.py
  test_commit_before_publish.py
```

No changes under `src/` (frontend). No SP1 contract field renames.

## 11. Decision notes

1. **WAL + synchronous=NORMAL** — product-accepted durability; not FULL.
2. **Lock acquisition order = sequence order** — timestamps never authoritative.
3. **COMMIT before fan-out** — subscribers never see uncommitted events; crash mid-write leaves no partial row and no live delivery.
4. **Single publish lock + single journal thread** — simplicity over throughput; writer queue / async DB rejected for SP2.
5. **put_nowait + LAGGING** — publisher never blocks on subscribers; resync marker is control-plane only (not in `events` table).
6. **Triggers enforce append-only** — defense in depth beyond API discipline.
7. **revision only on state-mutating events** — sequence still advances for non-mutating (e.g. pure ticks if ever journaled); caller marks mutability.
8. **Full envelope JSON in journal** — indexed columns are projections for query; envelope is source for replay hydration.
9. **Commands dual table** — current row for O(1) poll/idempotency; transitions append-only for audit.
10. **No frontend contract deviation** — envelope shape remains SP1/TS; bus only fills `bootId`/`sequence`/`revision`.

## 12. Test plan (required)

| Case | Assert |
|---|---|
| Crash mid-write / reopen | kill/interrupt during insert before COMMIT (or inject failure); reopen DB; no partial row; next publish clean |
| Concurrent publish | many tasks; sequences strictly monotonic 1..N; no duplicates; total order matches commit order |
| Per-subscriber order | each subscriber receives increasing sequence; no reorder |
| Replay | `read_events(boot, after, limit)` after-exclusive, boot-scoped, sequence ordered, bounded |
| Triggers | UPDATE/DELETE on `events` and `command_transitions` abort |
| Slow subscriber isolation | fast subscriber keeps receiving; slow one overflows; lagging count = 1 (or N); warning log contains subscriber id |
| Commit-before-publish | mock/spy: no queue item until COMMIT callback completed; if COMMIT fails, queues empty and counters restored |
| Command TX | transition + command current row atomic with paired event when bundled |

## 13. Self-review checklist (content)

- No `TBD` / `TODO` / placeholder APIs.
- Sequence vs revision roles not conflated.
- Overflow clears queue then enqueues resync marker under same atomic handling.
- Replay API signature and semantics fixed.
- Rejected designs recorded once; not reopened in implementation without new decision.
- Frontend contract untouched; MANUAL vs MANUAL_CLOSE remains SP1 decision (out of SP2).
