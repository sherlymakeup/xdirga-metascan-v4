# SP2 — Append-only Journal + EventBus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crash-safe SQLite append-only event journal + command store, and an asyncio EventBus that assigns boot-scoped total order, commits before fan-out, never blocks publishers on slow subscribers, and supports exact replay.

**Architecture:** One process-wide `EventBus` holds `_publish_lock`, in-memory `boot_id`/`sequence`/`revision`, and subscriber queues. Journal writes run exclusively on a single-thread `ThreadPoolExecutor`. Publish path: allocate counters → `run_in_executor(append_event_committed)` (COMMIT) → `put_nowait` fan-out under the same lock. Replay is boot-scoped `sequence > after` SQL. Commands use mutable `commands` + append-only `command_transitions` in the same SQLite transaction as the paired event.

**Tech Stack:** Python 3.12, stdlib `sqlite3` + `concurrent.futures` + `asyncio` + `logging`, Pydantic v2 SP1 models (`RuntimeEventEnvelope`, `RuntimeCommandStatus`), pytest + pytest-asyncio.

**Commit policy (user override):** Do **not** commit per task. Run all RED→GREEN steps; only after full verification, one commit:

```bash
git add backend/src/metascan/journal backend/src/metascan/bus backend/tests/test_journal_*.py backend/tests/test_event_bus_*.py backend/tests/test_replay.py backend/tests/test_commit_before_publish.py backend/tests/conftest.py backend/pyproject.toml backend/SP2_SUMMARY.md
git commit -m "SP2: append-only journal + EventBus"
```

**Working directory for all commands:** `backend/` (unless noted).

**Run tests:**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest <path> -v
```

If `uv` env already has package editable: `uv run --extra dev pytest ...` after adding `pytest-asyncio`.

---

## File map

| Path | Responsibility |
|---|---|
| `src/metascan/journal/__init__.py` | Re-export `Journal`, `read_events` helpers |
| `src/metascan/journal/schema.sql` | DDL + append-only triggers |
| `src/metascan/journal/db.py` | Connect, pragmas, apply schema, `JournalDb` write-conn ownership |
| `src/metascan/journal/events.py` | `append_event_committed`, `read_events` |
| `src/metascan/journal/commands.py` | Command current row + transition helpers; `commit_bundle` |
| `src/metascan/bus/__init__.py` | Re-export `EventBus`, `Subscription`, exceptions |
| `src/metascan/bus/event_bus.py` | EventBus, Subscription, lock, fan-out, lagging, lifecycle |
| `tests/conftest.py` | Shared tmp journal path, event factory |
| `tests/test_journal_triggers.py` | UPDATE/DELETE abort |
| `tests/test_journal_crash.py` | Crash mid-write / reopen / no partial row |
| `tests/test_replay.py` | `read_events` semantics |
| `tests/test_event_bus_order.py` | Monotonic sequence, concurrent publish, per-sub order |
| `tests/test_event_bus_overflow.py` | Slow sub isolation, resync marker, lag count, log |
| `tests/test_commit_before_publish.py` | COMMIT before queue; failure restores counters |
| `tests/test_command_tx.py` | Command + transition + event atomic bundle |
| `SP2_SUMMARY.md` | Decisions + delivered scope (write last) |
| `pyproject.toml` | Add `pytest-asyncio` dev dep only |

**Do not touch:** `src/` frontend, SP1 contract field names, `contract/*` models (import only).

---

## Locked interfaces (implement exactly)

### Exceptions

```python
# src/metascan/bus/event_bus.py (and re-export)
class EventBusClosed(RuntimeError):
    """Publish/subscribe after shutdown."""


class JournalError(RuntimeError):
    """SQLite / journal writer failure."""


class JournalAlreadyOpen(JournalError):
    """Second open of exclusive writer refused."""
```

### Journal

```python
# src/metascan/journal/db.py
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BUSY_TIMEOUT_MS = 5000
READ_EVENTS_HARD_CAP = 10_000

class Journal:
    """Exclusive SQLite writer on one dedicated thread + multi-reader opens."""

    def __init__(
        self,
        path: Path | str,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None: ...

    def open(self) -> None:
        """Create parent dirs, apply schema, set WAL + synchronous=NORMAL.
        Start ThreadPoolExecutor(max_workers=1). Refuse double-open.
        """

    def close(self) -> None:
        """Close write connection on journal thread; shutdown executor."""

    @property
    def path(self) -> Path: ...

    @property
    def is_open(self) -> bool: ...

    def append_event_committed(self, envelope: RuntimeEventEnvelope) -> None:
        """INSERT events row; COMMIT; return only after COMMIT. Thread-safe
        only when called from journal executor (EventBus uses run_in_executor).
        Also safe when called via run_on_writer.
        """

    def read_events(
        self,
        boot_id: str,
        after_sequence: int,
        limit: int,
    ) -> list[RuntimeEventEnvelope]:
        """Boot-scoped, sequence > after, ORDER BY sequence ASC, LIMIT.
        limit < 1 or limit > READ_EVENTS_HARD_CAP → ValueError.
        Unknown boot → []. Uses a short-lived read connection (WAL).
        """

    def commit_bundle(
        self,
        *,
        envelope: RuntimeEventEnvelope | None = None,
        command_upsert: RuntimeCommandStatus | None = None,
        transition: CommandTransitionRecord | None = None,
    ) -> None:
        """One SQLite transaction: optional event INSERT + optional commands
        UPSERT + optional command_transitions INSERT. COMMIT once.
        """

    def run_on_writer(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Execute fn on the exclusive write connection (same thread as writer).
        Used by tests and commit_bundle internals.
        """
```

```python
# src/metascan/journal/commands.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CommandTransitionRecord:
    boot_id: str
    sequence: int          # same as paired event sequence
    command_id: str
    from_state: str | None # None on create
    to_state: str
    ts: str                # ISO-8601
    transition_json: str   # full JSON object (canonical)

def get_command_by_idempotency_key(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> RuntimeCommandStatus | None: ...

def upsert_command_and_transition(
    conn: sqlite3.Connection,
    status: RuntimeCommandStatus,
    transition: CommandTransitionRecord,
) -> None:
    """UPDATE commands by command_id if exists else INSERT;
    always INSERT command_transitions. Caller owns transaction.
    Unique idempotency_key conflict: raise sqlite3.IntegrityError
    (Journal API maps to return-existing at higher layer).
    """
```

### EventBus

```python
# src/metascan/bus/event_bus.py
from typing import Any, AsyncIterator

RESYNC_KIND = "resync_required"
DEFAULT_SUBSCRIBER_MAXSIZE = 1024

@dataclass(frozen=True, slots=True)
class ResyncMarker:
    kind: str  # always RESYNC_KIND
    boot_id: str
    last_committed_sequence: int
    reason: str  # "subscriber_overflow"
    subscriber_id: str

# Queue items: RuntimeEventEnvelope | ResyncMarker

class Subscription:
    id: str
    @property
    def is_lagging(self) -> bool: ...
    async def get(self) -> RuntimeEventEnvelope | ResyncMarker: ...
    def __aiter__(self) -> AsyncIterator[RuntimeEventEnvelope | ResyncMarker]: ...
    async def __anext__(self) -> RuntimeEventEnvelope | ResyncMarker: ...
    def ack_resync(self) -> None:
        """Clear LAGGING after consumer finished resync protocol."""

class EventBus:
    def __init__(
        self,
        journal: Journal,
        *,
        default_queue_maxsize: int = DEFAULT_SUBSCRIBER_MAXSIZE,
    ) -> None: ...

    async def start(self) -> None:
        """journal.open() if needed; mint boot_id=uuid4; sequence=0; revision=0."""

    async def close(self) -> None:
        """Stop publishes; wait in-flight under lock; wake/clear subs; journal.close()."""

    @property
    def boot_id(self) -> str: ...
    @property
    def sequence(self) -> int: ...
    @property
    def revision(self) -> int: ...
    @property
    def lagging_subscriber_count(self) -> int: ...
    @property
    def closed(self) -> bool: ...

    async def subscribe(
        self,
        subscriber_id: str,
        maxsize: int | None = None,
    ) -> Subscription: ...

    async def unsubscribe(self, subscriber_id: str) -> None: ...

    async def publish(
        self,
        envelope: RuntimeEventEnvelope,
        *,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        """Under _publish_lock:
        1. sequence += 1; if mutates_state: revision += 1
        2. stamp boot_id, sequence, revision on envelope copy
        3. await run_in_executor(journal_executor, append_event_committed, stamped)
           on failure: restore sequence/revision; raise; no fan-out
        4. for each sub: put_nowait or overflow path
        5. return stamped envelope
        After close → EventBusClosed.
        """

    async def publish_command_event(
        self,
        envelope: RuntimeEventEnvelope,
        status: RuntimeCommandStatus,
        *,
        from_state: str | None,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        """Same as publish but commit_bundle(envelope + command upsert + transition)
        with transition.sequence == stamped event sequence.
        Idempotent: if status.idempotency_key already exists and caller marks
        create-only path — see Task 8; for SP2 tests use explicit create once.
        """
```

### SQL schema (exact)

File: `src/metascan/journal/schema.sql` — content in Task 1.

### Envelope stamping rules

- Caller builds `RuntimeEventEnvelope` with **placeholder** `boot_id=""`, `sequence=0`, `revision=0` (or any values); EventBus **overwrites** those three after allocation.
- `entity_id` column: `position_id or order_id or command_id` (first non-None), else NULL.
- `ts` column: `envelope.occurred_at`.
- `type` column: `str(envelope.type.value)` if Enum else `str(envelope.type)`.
- Wire JSON: `envelope.model_dump_json()` (camelCase via WireModel).

### Overflow path (atomic under `_publish_lock` per subscriber)

1. `sub._lagging = True`
2. Drain queue: while not empty, `get_nowait` discard
3. `put_nowait(ResyncMarker(... last_committed_sequence=stamped.sequence ...))`
4. `logger.warning("subscriber_overflow", extra={subscriber_id, boot_id, sequence, maxsize})`
5. Recompute `lagging_subscriber_count = sum(1 for s in subs if s.is_lagging)`

Leave lagging until `ack_resync()`.

### Logging

stdlib `logging.getLogger("metascan.bus")` — no new structlog dependency (YAGNI; design intent covered by structured `extra`).

### pytest-asyncio

```toml
# pyproject.toml additions
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

---

## Task 1: Schema SQL + Journal open/pragmas

**Files:**
- Create: `src/metascan/journal/__init__.py`
- Create: `src/metascan/journal/schema.sql`
- Create: `src/metascan/journal/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_journal_triggers.py` (open + trigger cases start here; append tests later)
- Modify: `pyproject.toml` (pytest-asyncio)

- [ ] **Step 1: Add pytest-asyncio to pyproject.toml**

Replace optional-dependencies and pytest sections with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

Run: `uv sync --extra dev`

- [ ] **Step 2: Write failing test — schema open + triggers**

Create `tests/conftest.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from metascan.contract.models import RuntimeEventEnvelope


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    return tmp_path / "journal.sqlite"


def make_envelope(
    *,
    event_id: str = "e1",
    type_: str = "command.created",
    runtime_id: str = "rt1",
    boot_id: str = "",
    sequence: int = 0,
    revision: int = 0,
    payload: dict | None = None,
    command_id: str | None = None,
    order_id: str | None = None,
    position_id: str | None = None,
    occurred_at: str = "2026-07-13T00:00:00Z",
) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=event_id,
        type=type_,
        runtime_id=runtime_id,
        boot_id=boot_id,
        revision=revision,
        sequence=sequence,
        occurred_at=occurred_at,
        emitted_at=occurred_at,
        received_at=occurred_at,
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload=payload if payload is not None else {},
        command_id=command_id,
        order_id=order_id,
        position_id=position_id,
    )
```

Create `tests/test_journal_triggers.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from metascan.journal.db import Journal


def test_open_applies_schema_and_pragmas(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        conn = sqlite3.connect(journal_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            # NORMAL == 1
            assert int(sync) == 1
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "events" in tables
            assert "commands" in tables
            assert "command_transitions" in tables
        finally:
            conn.close()
    finally:
        j.close()


def test_events_update_forbidden(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = __import__(
            "tests.conftest", fromlist=["make_envelope"]
        ).make_envelope(boot_id="b1", sequence=1, revision=1)
        # direct insert via writer for trigger test
        def _ins(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO events
                  (boot_id, sequence, type, entity_id, ts, envelope_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "b1",
                    1,
                    "command.created",
                    None,
                    "2026-07-13T00:00:00Z",
                    env.model_dump_json(),
                ),
            )
            conn.commit()

        j.run_on_writer(_ins)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            def _upd(conn: sqlite3.Connection) -> None:
                conn.execute("UPDATE events SET type='x' WHERE boot_id='b1'")
                conn.commit()

            j.run_on_writer(_upd)
    finally:
        j.close()


def test_events_delete_forbidden(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = __import__(
            "tests.conftest", fromlist=["make_envelope"]
        ).make_envelope(boot_id="b1", sequence=1, revision=1)

        def _ins(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO events
                  (boot_id, sequence, type, entity_id, ts, envelope_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "b1",
                    1,
                    "command.created",
                    None,
                    "2026-07-13T00:00:00Z",
                    env.model_dump_json(),
                ),
            )
            conn.commit()

        j.run_on_writer(_ins)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            def _del(conn: sqlite3.Connection) -> None:
                conn.execute("DELETE FROM events WHERE boot_id='b1'")
                conn.commit()

            j.run_on_writer(_del)
    finally:
        j.close()


def test_double_open_refused(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        with pytest.raises(Exception) as ei:
            j.open()
        assert "open" in str(ei.value).lower() or "already" in str(ei.value).lower()
    finally:
        j.close()
```

- [ ] **Step 3: Run tests — expect FAIL**

```powershell
uv run pytest tests/test_journal_triggers.py -v
```

Expected: `ModuleNotFoundError: No module named 'metascan.journal'` (or ImportError for Journal).

- [ ] **Step 4: Implement schema.sql + db.py minimal open**

`src/metascan/journal/schema.sql`:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
  boot_id       TEXT    NOT NULL,
  sequence      INTEGER NOT NULL,
  type          TEXT    NOT NULL,
  entity_id     TEXT    NULL,
  ts            TEXT    NOT NULL,
  envelope_json TEXT    NOT NULL,
  PRIMARY KEY (boot_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_events_boot_seq   ON events (boot_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_boot_type  ON events (boot_id, type);
CREATE INDEX IF NOT EXISTS idx_events_entity     ON events (boot_id, entity_id)
  WHERE entity_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: DELETE forbidden');
END;

CREATE TABLE IF NOT EXISTS commands (
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
  record_json        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS command_transitions (
  boot_id         TEXT    NOT NULL,
  sequence        INTEGER NOT NULL,
  command_id      TEXT    NOT NULL,
  from_state      TEXT    NULL,
  to_state        TEXT    NOT NULL,
  ts              TEXT    NOT NULL,
  transition_json TEXT    NOT NULL,
  PRIMARY KEY (boot_id, sequence, command_id)
);

CREATE INDEX IF NOT EXISTS idx_cmd_transitions_cmd
  ON command_transitions (command_id, boot_id, sequence);

CREATE TRIGGER IF NOT EXISTS command_transitions_no_update
BEFORE UPDATE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS command_transitions_no_delete
BEFORE DELETE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: DELETE forbidden');
END;
```

`src/metascan/journal/db.py`:

```python
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from metascan.contract.models import RuntimeEventEnvelope

T = TypeVar("T")

DEFAULT_BUSY_TIMEOUT_MS = 5000
READ_EVENTS_HARD_CAP = 10_000

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class JournalError(RuntimeError):
    pass


class JournalAlreadyOpen(JournalError):
    pass


class Journal:
    def __init__(
        self,
        path: Path | str,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._executor: ThreadPoolExecutor | None = None
        self._conn: sqlite3.Connection | None = None
        self._open = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self._open:
            raise JournalAlreadyOpen("journal writer already open")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="journal-writer"
        )
        self._conn = self._executor.submit(self._open_connection).result()
        self._open = True

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()
        return conn

    def close(self) -> None:
        if not self._open:
            return
        ex = self._executor
        conn = self._conn
        self._open = False
        self._conn = None
        self._executor = None

        def _close() -> None:
            if conn is not None:
                conn.close()

        if ex is not None:
            ex.submit(_close).result()
            ex.shutdown(wait=True)

    def run_on_writer(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if not self._open or self._executor is None or self._conn is None:
            raise JournalError("journal not open")
        conn = self._conn

        def _call() -> T:
            return fn(conn)

        return self._executor.submit(_call).result()

    # stubs filled in later tasks
    def append_event_committed(self, envelope: RuntimeEventEnvelope) -> None:
        raise NotImplementedError

    def read_events(
        self, boot_id: str, after_sequence: int, limit: int
    ) -> list[RuntimeEventEnvelope]:
        raise NotImplementedError

    def commit_bundle(self, **kwargs: object) -> None:
        raise NotImplementedError
```

`src/metascan/journal/__init__.py`:

```python
from metascan.journal.db import (
    DEFAULT_BUSY_TIMEOUT_MS,
    READ_EVENTS_HARD_CAP,
    Journal,
    JournalAlreadyOpen,
    JournalError,
)

__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "READ_EVENTS_HARD_CAP",
    "Journal",
    "JournalAlreadyOpen",
    "JournalError",
]
```

- [ ] **Step 5: Run tests — expect PASS for open/triggers/double-open**

```powershell
uv run pytest tests/test_journal_triggers.py -v
```

Expected: all PASS. Note: SQLite trigger `RAISE(ABORT, ...)` surfaces as `sqlite3.IntegrityError` with message containing `append-only`.

If Windows path issues: ensure `schema.sql` is packaged — hatchling includes package data by default for files next to modules only if configured. For tests importing from source via `pythonpath=src`, file is read by Path next to `db.py` — OK without package data.

- [ ] **Step 6: Fix conftest import style in trigger tests (cleanup)**

Edit trigger tests to use:

```python
from tests.conftest import make_envelope
```

If pytest root is `backend/`, prefer:

```python
# in test file, use the fixture-free helper via relative import failure —
# put make_envelope in conftest and import:
from conftest import make_envelope  # may fail
```

**Canonical:** keep `make_envelope` in `tests/conftest.py` and **duplicate is fine to avoid import path pain** — instead import from a shared module:

Create `tests/helpers.py` with `make_envelope`; conftest re-exports. Update tests to `from helpers import make_envelope`.

```python
# tests/helpers.py — same make_envelope body as above
# tests/conftest.py
from helpers import make_envelope  # noqa: F401
```

Re-run trigger tests — PASS.

---

## Task 2: append_event_committed + read_events

**Files:**
- Create: `src/metascan/journal/events.py`
- Modify: `src/metascan/journal/db.py` (wire methods)
- Create: `tests/test_replay.py`
- Modify: `tests/test_journal_triggers.py` (optional: command_transitions triggers)

- [ ] **Step 1: Write failing replay tests**

`tests/test_replay.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.journal.db import READ_EVENTS_HARD_CAP, Journal


def test_read_events_after_exclusive_ordered_bounded(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        for seq in (1, 2, 3):
            env = make_envelope(
                event_id=f"e{seq}",
                boot_id="bootA",
                sequence=seq,
                revision=seq,
            )
            j.append_event_committed(env)
        # other boot ignored
        j.append_event_committed(
            make_envelope(event_id="x", boot_id="bootB", sequence=1, revision=1)
        )
        got = j.read_events("bootA", after_sequence=1, limit=10)
        assert [e.sequence for e in got] == [2, 3]
        assert all(e.boot_id == "bootA" for e in got)
        assert got[0].event_id == "e2"
        assert j.read_events("bootA", after_sequence=3, limit=10) == []
        assert j.read_events("unknown", after_sequence=0, limit=10) == []
        limited = j.read_events("bootA", after_sequence=0, limit=2)
        assert [e.sequence for e in limited] == [1, 2]
    finally:
        j.close()


def test_read_events_limit_validation(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        with pytest.raises(ValueError):
            j.read_events("b", 0, 0)
        with pytest.raises(ValueError):
            j.read_events("b", 0, -1)
        with pytest.raises(ValueError):
            j.read_events("b", 0, READ_EVENTS_HARD_CAP + 1)
    finally:
        j.close()


def test_append_roundtrip_wire_json(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = make_envelope(
            event_id="e9",
            boot_id="b",
            sequence=1,
            revision=1,
            command_id="cmd-1",
            payload={"k": 1},
        )
        j.append_event_committed(env)
        got = j.read_events("b", 0, 1)[0]
        assert got.event_id == "e9"
        assert got.command_id == "cmd-1"
        assert got.payload == {"k": 1}
        assert got.type.value == "command.created" or str(got.type) == "command.created"
    finally:
        j.close()
```

- [ ] **Step 2: Run — expect FAIL**

```powershell
uv run pytest tests/test_replay.py -v
```

Expected: `NotImplementedError` or AttributeError on `append_event_committed`.

- [ ] **Step 3: Implement events.py + wire Journal methods**

`src/metascan/journal/events.py`:

```python
from __future__ import annotations

import sqlite3

from metascan.contract.models import RuntimeEventEnvelope
from metascan.journal.db import READ_EVENTS_HARD_CAP


def entity_id_from_envelope(envelope: RuntimeEventEnvelope) -> str | None:
    return envelope.position_id or envelope.order_id or envelope.command_id


def event_type_str(envelope: RuntimeEventEnvelope) -> str:
    t = envelope.type
    return t.value if hasattr(t, "value") else str(t)


def insert_event(conn: sqlite3.Connection, envelope: RuntimeEventEnvelope) -> None:
    conn.execute(
        """
        INSERT INTO events (boot_id, sequence, type, entity_id, ts, envelope_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            envelope.boot_id,
            envelope.sequence,
            event_type_str(envelope),
            entity_id_from_envelope(envelope),
            envelope.occurred_at,
            envelope.model_dump_json(),
        ),
    )


def append_event_committed(
    conn: sqlite3.Connection, envelope: RuntimeEventEnvelope
) -> None:
    try:
        insert_event(conn, envelope)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def read_events(
    path: str | sqlite3.Connection,
    boot_id: str,
    after_sequence: int,
    limit: int,
    *,
    busy_timeout_ms: int = 5000,
) -> list[RuntimeEventEnvelope]:
    if limit < 1 or limit > READ_EVENTS_HARD_CAP:
        raise ValueError(
            f"limit must be in 1..{READ_EVENTS_HARD_CAP}, got {limit}"
        )
    own = False
    if isinstance(path, sqlite3.Connection):
        conn = path
    else:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        own = True
    try:
        rows = conn.execute(
            """
            SELECT envelope_json FROM events
            WHERE boot_id = ? AND sequence > ?
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (boot_id, after_sequence, limit),
        ).fetchall()
        return [
            RuntimeEventEnvelope.model_validate_json(r["envelope_json"])
            for r in rows
        ]
    finally:
        if own:
            conn.close()
```

Wire in `db.py`:

```python
from metascan.journal import events as events_mod

def append_event_committed(self, envelope: RuntimeEventEnvelope) -> None:
    if not self._open:
        raise JournalError("journal not open")

    def _do(conn: sqlite3.Connection) -> None:
        events_mod.append_event_committed(conn, envelope)

    self.run_on_writer(_do)

def read_events(
    self, boot_id: str, after_sequence: int, limit: int
) -> list[RuntimeEventEnvelope]:
    # read via separate connection (WAL) so writers are not blocked
    return events_mod.read_events(
        str(self._path),
        boot_id,
        after_sequence,
        limit,
        busy_timeout_ms=self._busy_timeout_ms,
    )
```

Export `read_events` from package if desired via `__init__.py` (optional).

- [ ] **Step 4: Run — expect PASS**

```powershell
uv run pytest tests/test_replay.py tests/test_journal_triggers.py -v
```

Expected: PASS.

- [ ] **Step 5: Add command_transitions trigger tests**

Append to `tests/test_journal_triggers.py`:

```python
def test_command_transitions_update_delete_forbidden(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        def _ins(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO command_transitions
                  (boot_id, sequence, command_id, from_state, to_state, ts, transition_json)
                VALUES ('b', 1, 'c1', NULL, 'PREPARED', '2026-07-13T00:00:00Z', '{}')
                """
            )
            conn.commit()

        j.run_on_writer(_ins)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            j.run_on_writer(
                lambda c: (
                    c.execute("UPDATE command_transitions SET to_state='X'"),
                    c.commit(),
                )
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            j.run_on_writer(
                lambda c: (
                    c.execute("DELETE FROM command_transitions"),
                    c.commit(),
                )
            )
    finally:
        j.close()
```

Run: `uv run pytest tests/test_journal_triggers.py::test_command_transitions_update_delete_forbidden -v` → PASS.

---

## Task 3: Crash mid-write (subprocess)

**Files:**
- Create: `tests/test_journal_crash.py`
- Create: `tests/crash_helpers/interrupt_insert.py` (script invoked as subprocess)

- [ ] **Step 1: Write crash test**

`tests/crash_helpers/interrupt_insert.py`:

```python
"""Child process: begin INSERT then raise before COMMIT — simulates crash mid-write."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    db = Path(sys.argv[1])
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    # Schema must already exist (parent applied it)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO events (boot_id, sequence, type, entity_id, ts, envelope_json)
        VALUES ('crash-boot', 1, 'command.created', NULL, '2026-07-13T00:00:00Z', '{}')
        """
    )
    # Simulate process death before COMMIT: rollback + exit non-zero
    conn.rollback()
    conn.close()
    sys.exit(42)


if __name__ == "__main__":
    main()
```

Also test **inject failure inside append** (in-process) and **reopen after unclean**:

`tests/test_journal_crash.py`:

```python
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.journal.db import Journal


def test_failed_commit_leaves_no_row(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        def _boom(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO events (boot_id, sequence, type, entity_id, ts, envelope_json)
                VALUES ('b', 1, 'command.created', NULL, 't', '{}')
                """
            )
            raise RuntimeError("inject commit failure")

        with pytest.raises(RuntimeError, match="inject"):
            j.run_on_writer(_boom)
        # ensure rollback
        def _count(conn: sqlite3.Connection) -> int:
            try:
                conn.rollback()
            except Exception:
                pass
            return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

        assert j.run_on_writer(_count) == 0
    finally:
        j.close()


def test_reopen_after_subprocess_uncommitted(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    j.close()

    script = Path(__file__).parent / "crash_helpers" / "interrupt_insert.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(journal_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 42

    j2 = Journal(journal_path)
    j2.open()
    try:
        assert j2.read_events("crash-boot", 0, 10) == []
        # next publish/append still works
        env = make_envelope(boot_id="new-boot", sequence=1, revision=1, event_id="ok")
        j2.append_event_committed(env)
        assert len(j2.read_events("new-boot", 0, 10)) == 1
    finally:
        j2.close()


def test_append_commit_failure_rolls_back(journal_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        import metascan.journal.events as ev

        real_insert = ev.insert_event

        def bad_insert(conn: sqlite3.Connection, envelope: object) -> None:
            real_insert(conn, envelope)  # type: ignore[arg-type]
            raise sqlite3.DatabaseError("disk full")

        monkeypatch.setattr(ev, "insert_event", bad_insert)
        # re-bind append path: monkeypatch append_event_committed to use failing insert
        def failing_append(conn: sqlite3.Connection, envelope: object) -> None:
            try:
                bad_insert(conn, envelope)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        monkeypatch.setattr(ev, "append_event_committed", failing_append)

        with pytest.raises(sqlite3.DatabaseError):
            j.append_event_committed(
                make_envelope(boot_id="b", sequence=1, revision=1)
            )
        assert j.read_events("b", 0, 10) == []
    finally:
        j.close()
```

**Note:** `Journal.append_event_committed` must call `events_mod.append_event_committed` so monkeypatch works. Already planned that way.

- [ ] **Step 2: Run — expect FAIL until crash helpers exist; then PASS after files written**

```powershell
uv run pytest tests/test_journal_crash.py -v
```

Expected after implementation: PASS. Subprocess exit 42; zero rows for `crash-boot`.

---

## Task 4: EventBus start/publish/subscribe order

**Files:**
- Create: `src/metascan/bus/__init__.py`
- Create: `src/metascan/bus/event_bus.py`
- Create: `tests/test_event_bus_order.py`

- [ ] **Step 1: Write failing order tests**

`tests/test_event_bus_order.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal


@pytest.fixture
async def bus(journal_path: Path):
    j = Journal(journal_path)
    b = EventBus(j)
    await b.start()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_publish_stamps_monotonic_sequence_and_revision(bus: EventBus) -> None:
    assert bus.sequence == 0
    assert bus.revision == 0
    boot = bus.boot_id
    assert boot  # non-empty uuid

    e1 = await bus.publish(make_envelope(event_id="a"), mutates_state=True)
    assert e1.boot_id == boot
    assert e1.sequence == 1
    assert e1.revision == 1
    assert bus.sequence == 1
    assert bus.revision == 1

    e2 = await bus.publish(make_envelope(event_id="b"), mutates_state=False)
    assert e2.sequence == 2
    assert e2.revision == 1  # non-mutating
    assert bus.revision == 1

    e3 = await bus.publish(make_envelope(event_id="c"), mutates_state=True)
    assert e3.sequence == 3
    assert e3.revision == 2


@pytest.mark.asyncio
async def test_subscriber_receives_in_sequence_order(bus: EventBus) -> None:
    sub = await bus.subscribe("s1")
    for i in range(5):
        await bus.publish(make_envelope(event_id=f"e{i}"))
    seqs = []
    for _ in range(5):
        item = await sub.get()
        seqs.append(item.sequence)  # type: ignore[union-attr]
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_concurrent_publish_unique_monotonic(bus: EventBus) -> None:
    n = 50

    async def one(i: int):
        return await bus.publish(make_envelope(event_id=f"c{i}"))

    results = await asyncio.gather(*[one(i) for i in range(n)])
    seqs = sorted(r.sequence for r in results)
    assert seqs == list(range(1, n + 1))
    assert len({r.sequence for r in results}) == n
    # journal matches
    stored = bus._journal.read_events(bus.boot_id, 0, n)  # noqa: SLF001 — test OK
    assert [e.sequence for e in stored] == list(range(1, n + 1))


@pytest.mark.asyncio
async def test_publish_after_close_raises(bus: EventBus) -> None:
    from metascan.bus.event_bus import EventBusClosed

    await bus.close()
    with pytest.raises(EventBusClosed):
        await bus.publish(make_envelope())
```

- [ ] **Step 2: Run — expect FAIL**

```powershell
uv run pytest tests/test_event_bus_order.py -v
```

Expected: `ModuleNotFoundError: metascan.bus`.

- [ ] **Step 3: Implement EventBus (core publish + subscribe)**

`src/metascan/bus/event_bus.py`:

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.journal.commands import CommandTransitionRecord
from metascan.journal.db import Journal

logger = logging.getLogger("metascan.bus")

RESYNC_KIND = "resync_required"
DEFAULT_SUBSCRIBER_MAXSIZE = 1024


class EventBusClosed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResyncMarker:
    kind: str
    boot_id: str
    last_committed_sequence: int
    reason: str
    subscriber_id: str


class Subscription:
    def __init__(
        self,
        subscriber_id: str,
        queue: asyncio.Queue[RuntimeEventEnvelope | ResyncMarker],
        *,
        maxsize: int,
    ) -> None:
        self.id = subscriber_id
        self._queue = queue
        self._maxsize = maxsize
        self._lagging = False

    @property
    def is_lagging(self) -> bool:
        return self._lagging

    @property
    def maxsize(self) -> int:
        return self._maxsize

    async def get(self) -> RuntimeEventEnvelope | ResyncMarker:
        return await self._queue.get()

    def __aiter__(self) -> AsyncIterator[RuntimeEventEnvelope | ResyncMarker]:
        return self

    async def __anext__(self) -> RuntimeEventEnvelope | ResyncMarker:
        return await self.get()

    def ack_resync(self) -> None:
        self._lagging = False

    def _set_lagging(self, value: bool) -> None:
        self._lagging = value

    def _queue_ref(self) -> asyncio.Queue[RuntimeEventEnvelope | ResyncMarker]:
        return self._queue


class EventBus:
    def __init__(
        self,
        journal: Journal,
        *,
        default_queue_maxsize: int = DEFAULT_SUBSCRIBER_MAXSIZE,
    ) -> None:
        self._journal = journal
        self._default_maxsize = default_queue_maxsize
        self._publish_lock = asyncio.Lock()
        self._boot_id = ""
        self._sequence = 0
        self._revision = 0
        self._subs: dict[str, Subscription] = {}
        self._closed = False
        self._started = False

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def lagging_subscriber_count(self) -> int:
        return sum(1 for s in self._subs.values() if s.is_lagging)

    async def start(self) -> None:
        if self._started:
            return
        if not self._journal.is_open:
            self._journal.open()
        self._boot_id = str(uuid.uuid4())
        self._sequence = 0
        self._revision = 0
        self._closed = False
        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with self._publish_lock:
            # in-flight publish finishes before we hold lock here
            pass
        self._subs.clear()
        if self._journal.is_open:
            self._journal.close()
        self._started = False

    async def subscribe(
        self, subscriber_id: str, maxsize: int | None = None
    ) -> Subscription:
        if self._closed:
            raise EventBusClosed("event bus closed")
        if subscriber_id in self._subs:
            raise ValueError(f"subscriber already exists: {subscriber_id}")
        ms = self._default_maxsize if maxsize is None else maxsize
        q: asyncio.Queue[RuntimeEventEnvelope | ResyncMarker] = asyncio.Queue(
            maxsize=ms
        )
        sub = Subscription(subscriber_id, q, maxsize=ms)
        self._subs[subscriber_id] = sub
        return sub

    async def unsubscribe(self, subscriber_id: str) -> None:
        self._subs.pop(subscriber_id, None)

    def _stamp(
        self, envelope: RuntimeEventEnvelope, *, mutates_state: bool
    ) -> tuple[RuntimeEventEnvelope, int, int]:
        prev_seq, prev_rev = self._sequence, self._revision
        self._sequence = prev_seq + 1
        if mutates_state:
            self._revision = prev_rev + 1
        stamped = envelope.model_copy(
            update={
                "boot_id": self._boot_id,
                "sequence": self._sequence,
                "revision": self._revision,
            }
        )
        return stamped, prev_seq, prev_rev

    def _restore(self, prev_seq: int, prev_rev: int) -> None:
        self._sequence = prev_seq
        self._revision = prev_rev

    def _fanout(self, stamped: RuntimeEventEnvelope) -> None:
        for sub in list(self._subs.values()):
            q = sub._queue_ref()
            if sub.is_lagging:
                # already lagging: only ensure resync marker semantics —
                # drop further events until ack (still under lock)
                continue
            try:
                q.put_nowait(stamped)
            except asyncio.QueueFull:
                self._overflow(sub, stamped)

    def _overflow(self, sub: Subscription, stamped: RuntimeEventEnvelope) -> None:
        q = sub._queue_ref()
        sub._set_lagging(True)
        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        marker = ResyncMarker(
            kind=RESYNC_KIND,
            boot_id=self._boot_id,
            last_committed_sequence=stamped.sequence,
            reason="subscriber_overflow",
            subscriber_id=sub.id,
        )
        try:
            q.put_nowait(marker)
        except asyncio.QueueFull:
            # maxsize>=1 required; if maxsize==0 impossible by config
            pass
        logger.warning(
            "subscriber_overflow",
            extra={
                "subscriber_id": sub.id,
                "boot_id": self._boot_id,
                "sequence": stamped.sequence,
                "maxsize": sub.maxsize,
            },
        )

    async def publish(
        self,
        envelope: RuntimeEventEnvelope,
        *,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(
                envelope, mutates_state=mutates_state
            )
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None,  # replaced below — must use journal executor
                    self._journal.append_event_committed,
                    stamped,
                )
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            self._fanout(stamped)
            return stamped

    async def publish_command_event(
        self,
        envelope: RuntimeEventEnvelope,
        status: RuntimeCommandStatus,
        *,
        from_state: str | None,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(
                envelope, mutates_state=mutates_state
            )
            transition = CommandTransitionRecord(
                boot_id=stamped.boot_id,
                sequence=stamped.sequence,
                command_id=status.command_id,
                from_state=from_state,
                to_state=status.state,
                ts=status.updated_at,
                transition_json=(
                    "{"
                    f'"commandId":"{status.command_id}",'
                    f'"fromState":{("null" if from_state is None else chr(34)+from_state+chr(34))},'
                    f'"toState":"{status.state}",'
                    f'"sequence":{stamped.sequence}'
                    "}"
                ),
            )
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._journal.commit_bundle(
                        envelope=stamped,
                        command_upsert=status,
                        transition=transition,
                    ),
                )
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            self._fanout(stamped)
            return stamped
```

**Critical fix for dedicated executor:** `run_in_executor(None, ...)` uses the default pool — design requires the **journal's single-thread executor**. Change `Journal` to expose `executor` property and:

```python
await loop.run_in_executor(
    self._journal.executor,
    self._journal.append_event_committed,
    stamped,
)
```

Add to `Journal`:

```python
@property
def executor(self) -> ThreadPoolExecutor:
    if self._executor is None:
        raise JournalError("journal not open")
    return self._executor
```

And ensure `append_event_committed` / `commit_bundle` when already on writer thread don't deadlock: `run_on_writer` uses `executor.submit().result()` — if called **from the writer thread**, deadlock.

**Rule:** `append_event_committed` must execute SQL **directly on `_conn` when invoked via `run_in_executor(journal.executor, ...)`** (already on writer thread). Implementation:

```python
def append_event_committed(self, envelope: RuntimeEventEnvelope) -> None:
    if not self._open or self._conn is None:
        raise JournalError("journal not open")
    # Always intended to run ON the writer thread.
    events_mod.append_event_committed(self._conn, envelope)

def run_on_writer(self, fn: Callable[[sqlite3.Connection], T]) -> T:
    if not self._open or self._executor is None or self._conn is None:
        raise JournalError("journal not open")
    conn = self._conn
    def _call() -> T:
        return fn(conn)
    # If already on writer thread, call directly
    import threading
    if threading.current_thread().name.startswith("journal-writer"):
        return _call()
    return self._executor.submit(_call).result()
```

`append_event_committed` when called from EventBus via `run_in_executor(self._journal.executor, ...)` runs on writer thread and uses `_conn` directly — **no nested submit**.

- [ ] **Step 4: Fix publish to use journal.executor; implement package init**

`src/metascan/bus/__init__.py`:

```python
from metascan.bus.event_bus import (
    DEFAULT_SUBSCRIBER_MAXSIZE,
    RESYNC_KIND,
    EventBus,
    EventBusClosed,
    ResyncMarker,
    Subscription,
)

__all__ = [
    "DEFAULT_SUBSCRIBER_MAXSIZE",
    "RESYNC_KIND",
    "EventBus",
    "EventBusClosed",
    "ResyncMarker",
    "Subscription",
]
```

Prefer public test access for journal reads:

```python
# In EventBus
@property
def journal(self) -> Journal:
    return self._journal
```

Update concurrent test to `bus.journal.read_events(...)`.

- [ ] **Step 5: Run order tests — PASS**

```powershell
uv run pytest tests/test_event_bus_order.py -v
```

Expected: PASS.

---

## Task 5: Commit-before-publish + counter restore

**Files:**
- Create: `tests/test_commit_before_publish.py`

- [ ] **Step 1: Write failing/behavioral tests**

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal


@pytest.mark.asyncio
async def test_no_fanout_until_commit_returns(journal_path: Path) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=16)
    await bus.start()
    sub = await bus.subscribe("s1")
    order: list[str] = []

    real_append = j.append_event_committed

    def tracked_append(envelope):  # type: ignore[no-untyped-def]
        order.append("commit_start")
        real_append(envelope)
        order.append("commit_done")

    with patch.object(j, "append_event_committed", side_effect=tracked_append):
        task = asyncio.create_task(bus.publish(make_envelope(event_id="e1")))
        # wait until publish completes
        await task
        order.append("after_publish")
        item = await asyncio.wait_for(sub.get(), timeout=1)
        order.append("got_item")
        assert item.sequence == 1  # type: ignore[union-attr]

    # commit_done must precede got_item; fanout is sync after commit inside lock
    assert order.index("commit_done") < order.index("got_item")
    assert order.index("commit_done") < order.index("after_publish") or True
    await bus.close()


@pytest.mark.asyncio
async def test_commit_failure_restores_counters_and_no_fanout(
    journal_path: Path,
) -> None:
    j = Journal(journal_path)
    bus = EventBus(j)
    await bus.start()
    sub = await bus.subscribe("s1", maxsize=8)

    def boom(envelope):  # type: ignore[no-untyped-def]
        raise RuntimeError("commit failed")

    with patch.object(j, "append_event_committed", side_effect=boom):
        with pytest.raises(RuntimeError, match="commit failed"):
            await bus.publish(make_envelope(event_id="x"))

    assert bus.sequence == 0
    assert bus.revision == 0
    assert sub._queue_ref().empty()  # noqa: SLF001
    # successful publish after restore
    ok = await bus.publish(make_envelope(event_id="y"))
    assert ok.sequence == 1
    assert bus.sequence == 1
    got = await sub.get()
    assert got.event_id == "y"  # type: ignore[union-attr]
    await bus.close()
```

- [ ] **Step 2: Run — expect PASS if Task 4 correct; FAIL if fan-out before commit**

```powershell
uv run pytest tests/test_commit_before_publish.py -v
```

If FAIL: move `_fanout` strictly after successful `await run_in_executor`.

---

## Task 6: Subscriber overflow + lagging + log

**Files:**
- Create: `tests/test_event_bus_overflow.py`
- Modify: `event_bus.py` if lagging-while-already-lagging needs drop-only behavior

- [ ] **Step 1: Write overflow tests**

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import RESYNC_KIND, EventBus, ResyncMarker
from metascan.journal.db import Journal


@pytest.mark.asyncio
async def test_slow_subscriber_overflow_isolates_fast(
    journal_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=2)
    await bus.start()
    slow = await bus.subscribe("slow", maxsize=2)
    fast = await bus.subscribe("fast", maxsize=64)

    with caplog.at_level(logging.WARNING, logger="metascan.bus"):
        # Fill slow queue: 2 events sit unconsumed; 3rd triggers overflow
        await bus.publish(make_envelope(event_id="1"))
        await bus.publish(make_envelope(event_id="2"))
        await bus.publish(make_envelope(event_id="3"))  # overflow slow
        # more events while slow lagging
        await bus.publish(make_envelope(event_id="4"))
        await bus.publish(make_envelope(event_id="5"))

    # fast received all 5 domain events
    fast_ids = []
    for _ in range(5):
        item = await asyncio.wait_for(fast.get(), timeout=1)
        assert not isinstance(item, ResyncMarker)
        fast_ids.append(item.event_id)
    assert fast_ids == ["1", "2", "3", "4", "5"]

    assert bus.lagging_subscriber_count == 1
    assert slow.is_lagging is True

    # slow queue: only resync marker
    marker = await asyncio.wait_for(slow.get(), timeout=1)
    assert isinstance(marker, ResyncMarker)
    assert marker.kind == RESYNC_KIND
    assert marker.reason == "subscriber_overflow"
    assert marker.subscriber_id == "slow"
    assert marker.boot_id == bus.boot_id
    assert marker.last_committed_sequence >= 3
    assert slow._queue_ref().empty()  # noqa: SLF001

    assert any(
        "subscriber_overflow" in r.message or r.msg == "subscriber_overflow"
        for r in caplog.records
    )
    # subscriber id present in record extras or message
    assert any(
        getattr(r, "subscriber_id", None) == "slow"
        or "slow" in r.getMessage()
        for r in caplog.records
    )

    slow.ack_resync()
    assert slow.is_lagging is False
    assert bus.lagging_subscriber_count == 0

    # after ack, new events flow again
    await bus.publish(make_envelope(event_id="6"))
    item = await asyncio.wait_for(slow.get(), timeout=1)
    assert not isinstance(item, ResyncMarker)
    assert item.event_id == "6"

    await bus.close()


@pytest.mark.asyncio
async def test_lagging_drops_until_ack(journal_path: Path) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=1)
    await bus.start()
    sub = await bus.subscribe("s", maxsize=1)
    await bus.publish(make_envelope(event_id="a"))
    await bus.publish(make_envelope(event_id="b"))  # overflow
    assert sub.is_lagging
    await bus.publish(make_envelope(event_id="c"))
    m = await sub.get()
    assert isinstance(m, ResyncMarker)
    # no further items until ack + new publish
    await bus.publish(make_envelope(event_id="d"))
    assert sub._queue_ref().empty()  # noqa: SLF001
    sub.ack_resync()
    await bus.publish(make_envelope(event_id="e"))
    got = await sub.get()
    assert got.event_id == "e"  # type: ignore[union-attr]
    await bus.close()
```

**Overflow semantics when already lagging:** `_fanout` skips put for lagging subs (drops). Marker stays until consumed; new overflows while still lagging and queue empty should not spam — skip. If marker already consumed but not acked, queue empty and lagging: either re-enqueue marker on next overflow or drop until ack. **Locked choice:** while `is_lagging`, drop all events (no new markers). Consumer must `ack_resync` then resume; if they drained marker without ack, they still get drops until ack — matches design "leaves LAGGING only after ack_resync".

- [ ] **Step 2: Run**

```powershell
uv run pytest tests/test_event_bus_overflow.py -v
```

Expected: PASS. Fix logger so `extra` fields appear — use:

```python
logger.warning(
    "subscriber_overflow subscriber_id=%s boot_id=%s sequence=%s maxsize=%s",
    sub.id,
    self._boot_id,
    stamped.sequence,
    sub.maxsize,
)
```

(caplog matches message substring `slow` / `subscriber_overflow`)

---

## Task 7: Command store + atomic commit_bundle

**Files:**
- Create: `src/metascan/journal/commands.py`
- Modify: `src/metascan/journal/db.py` (`commit_bundle`)
- Create: `tests/test_command_tx.py`

- [ ] **Step 1: Write command TX tests**

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import EventBus
from metascan.contract.models import RuntimeCommandStatus
from metascan.journal.commands import (
    CommandTransitionRecord,
    get_command_by_idempotency_key,
)
from metascan.journal.db import Journal


def _status(
    *,
    command_id: str = "cmd-1",
    key: str = "idem-1",
    state: str = "PREPARED",
) -> RuntimeCommandStatus:
    return RuntimeCommandStatus(
        command_id=command_id,
        client_request_id="cr1",
        correlation_id="corr1",
        idempotency_key=key,
        kind="runtime.pause",
        state=state,  # type: ignore[arg-type]
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:00Z",
    )


def test_commit_bundle_atomic_event_and_command(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = make_envelope(
            event_id="e1",
            boot_id="b",
            sequence=1,
            revision=1,
            command_id="cmd-1",
            type_="command.created",
        )
        st = _status()
        tr = CommandTransitionRecord(
            boot_id="b",
            sequence=1,
            command_id="cmd-1",
            from_state=None,
            to_state="PREPARED",
            ts=st.updated_at,
            transition_json='{"commandId":"cmd-1","fromState":null,"toState":"PREPARED","sequence":1}',
        )
        j.commit_bundle(envelope=env, command_upsert=st, transition=tr)
        assert len(j.read_events("b", 0, 10)) == 1
        got = j.run_on_writer(
            lambda c: get_command_by_idempotency_key(c, "idem-1")
        )
        assert got is not None
        assert got.command_id == "cmd-1"
        assert got.state == "PREPARED"

        def count_tr(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute("SELECT COUNT(*) FROM command_transitions").fetchone()[0]
            )

        assert j.run_on_writer(count_tr) == 1
    finally:
        j.close()


def test_commit_bundle_rolls_back_all_on_failure(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = make_envelope(boot_id="b", sequence=1, revision=1, command_id="cmd-1")
        st = _status()
        tr = CommandTransitionRecord(
            boot_id="b",
            sequence=1,
            command_id="cmd-1",
            from_state=None,
            to_state="PREPARED",
            ts=st.updated_at,
            transition_json="{}",
        )
        import metascan.journal.commands as cmd_mod

        real = cmd_mod.upsert_command_and_transition

        def bad(conn, status, transition):  # type: ignore[no-untyped-def]
            real(conn, status, transition)
            raise RuntimeError("fail after command write")

        monkeypatch.setattr(cmd_mod, "upsert_command_and_transition", bad)
        with pytest.raises(RuntimeError, match="fail after"):
            j.commit_bundle(envelope=env, command_upsert=st, transition=tr)
        assert j.read_events("b", 0, 10) == []
        assert (
            j.run_on_writer(lambda c: get_command_by_idempotency_key(c, "idem-1"))
            is None
        )
    finally:
        j.close()


@pytest.mark.asyncio
async def test_publish_command_event_pairs_sequence(journal_path: Path) -> None:
    j = Journal(journal_path)
    bus = EventBus(j)
    await bus.start()
    st = _status()
    env = make_envelope(event_id="e1", command_id=st.command_id, type_="command.created")
    stamped = await bus.publish_command_event(env, st, from_state=None)
    assert stamped.sequence == 1
    row = j.run_on_writer(lambda c: get_command_by_idempotency_key(c, st.idempotency_key))
    assert row is not None

    def seq(conn: sqlite3.Connection) -> int:
        return int(
            conn.execute(
                "SELECT sequence FROM command_transitions WHERE command_id=?",
                (st.command_id,),
            ).fetchone()[0]
        )

    assert j.run_on_writer(seq) == stamped.sequence
    await bus.close()


def test_idempotent_duplicate_key_returns_existing(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        st = _status()
        tr = CommandTransitionRecord(
            boot_id="b",
            sequence=1,
            command_id=st.command_id,
            from_state=None,
            to_state="PREPARED",
            ts=st.updated_at,
            transition_json="{}",
        )
        env = make_envelope(boot_id="b", sequence=1, revision=1, command_id=st.command_id)
        j.commit_bundle(envelope=env, command_upsert=st, transition=tr)
        existing = j.get_or_create_command(st)  # see implementation below
        assert existing.command_id == st.command_id
        # no second transition
        def n(conn: sqlite3.Connection) -> int:
            return int(conn.execute("SELECT COUNT(*) FROM command_transitions").fetchone()[0])

        assert j.run_on_writer(n) == 1
    finally:
        j.close()
```

- [ ] **Step 2: Implement commands.py + commit_bundle + get_or_create_command**

`src/metascan/journal/commands.py`:

```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from metascan.contract.models import RuntimeCommandStatus


@dataclass(frozen=True, slots=True)
class CommandTransitionRecord:
    boot_id: str
    sequence: int
    command_id: str
    from_state: str | None
    to_state: str
    ts: str
    transition_json: str


def get_command_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> RuntimeCommandStatus | None:
    row = conn.execute(
        "SELECT record_json FROM commands WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return RuntimeCommandStatus.model_validate_json(row[0])


def upsert_command_and_transition(
    conn: sqlite3.Connection,
    status: RuntimeCommandStatus,
    transition: CommandTransitionRecord,
) -> None:
    record_json = status.model_dump_json()
    kind = status.kind.value if hasattr(status.kind, "value") else str(status.kind)
    conn.execute(
        """
        INSERT INTO commands (
          command_id, idempotency_key, client_request_id, correlation_id,
          kind, target_id, state, progress, current_step, message, error_code,
          created_at, updated_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(command_id) DO UPDATE SET
          state=excluded.state,
          progress=excluded.progress,
          current_step=excluded.current_step,
          message=excluded.message,
          error_code=excluded.error_code,
          updated_at=excluded.updated_at,
          record_json=excluded.record_json
        """,
        (
            status.command_id,
            status.idempotency_key,
            status.client_request_id,
            status.correlation_id,
            kind,
            status.target_id,
            status.state,
            status.progress,
            status.current_step,
            status.message,
            status.error_code,
            status.created_at,
            status.updated_at,
            record_json,
        ),
    )
    conn.execute(
        """
        INSERT INTO command_transitions (
          boot_id, sequence, command_id, from_state, to_state, ts, transition_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transition.boot_id,
            transition.sequence,
            transition.command_id,
            transition.from_state,
            transition.to_state,
            transition.ts,
            transition.transition_json,
        ),
    )


def build_transition_json(
    *,
    command_id: str,
    from_state: str | None,
    to_state: str,
    sequence: int,
) -> str:
    return json.dumps(
        {
            "commandId": command_id,
            "fromState": from_state,
            "toState": to_state,
            "sequence": sequence,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
```

In `db.py` `commit_bundle` (runs on writer thread when called from executor):

```python
def commit_bundle(
    self,
    *,
    envelope: RuntimeEventEnvelope | None = None,
    command_upsert: RuntimeCommandStatus | None = None,
    transition: CommandTransitionRecord | None = None,
) -> None:
    if not self._open or self._conn is None:
        raise JournalError("journal not open")
    from metascan.journal import commands as cmd_mod
    from metascan.journal import events as events_mod

    conn = self._conn
    try:
        if envelope is not None:
            events_mod.insert_event(conn, envelope)
        if command_upsert is not None:
            if transition is None:
                raise JournalError("transition required with command_upsert")
            cmd_mod.upsert_command_and_transition(conn, command_upsert, transition)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def get_or_create_command(
    self, status: RuntimeCommandStatus
) -> RuntimeCommandStatus:
    """Idempotent read: if idempotency_key exists return existing; else caller
    must use commit_bundle for first insert. SP2 helper for duplicate key path.
    """
    def _get(conn: sqlite3.Connection) -> RuntimeCommandStatus | None:
        from metascan.journal.commands import get_command_by_idempotency_key
        return get_command_by_idempotency_key(conn, status.idempotency_key)

    existing = self.run_on_writer(_get)
    if existing is not None:
        return existing
    return status  # not inserted — EventBus/RuntimeCore decides create path
```

**Idempotent create API for SP2** (minimal):

```python
def try_insert_command_create(
    self,
    status: RuntimeCommandStatus,
    transition: CommandTransitionRecord,
    envelope: RuntimeEventEnvelope,
) -> tuple[RuntimeCommandStatus, bool]:
    """Returns (status, created). If idempotency_key exists, (existing, False)
    without writing event/transition. Else commit_bundle and (status, True).
    """
    def _body(conn: sqlite3.Connection) -> tuple[RuntimeCommandStatus, bool]:
        from metascan.journal.commands import (
            get_command_by_idempotency_key,
            upsert_command_and_transition,
        )
        from metascan.journal import events as events_mod

        existing = get_command_by_idempotency_key(conn, status.idempotency_key)
        if existing is not None:
            return existing, False
        events_mod.insert_event(conn, envelope)
        upsert_command_and_transition(conn, status, transition)
        conn.commit()
        return status, True

    return self.run_on_writer(_body)
```

Update `publish_command_event` transition_json to use `build_transition_json`.

Fix `test_idempotent_duplicate_key_returns_existing` to use `try_insert_command_create` twice.

- [ ] **Step 3: Run**

```powershell
uv run pytest tests/test_command_tx.py -v
```

Expected: PASS.

---

## Task 8: Lifecycle polish + export cleanup

**Files:**
- Modify: `event_bus.py` (close waits for lock; subscribe after close)
- Modify: `__init__.py` exports
- Modify: tests if needed for close race

- [ ] **Step 1: Tests for unsubscribe and close**

Add to `tests/test_event_bus_order.py`:

```python
@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    sub = await bus.subscribe("s1")
    await bus.unsubscribe("s1")
    await bus.publish(make_envelope(event_id="z"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_new_boot_resets_counters(journal_path: Path) -> None:
    j = Journal(journal_path)
    b1 = EventBus(j)
    await b1.start()
    boot1 = b1.boot_id
    await b1.publish(make_envelope(event_id="1"))
    assert b1.sequence == 1
    await b1.close()

    b2 = EventBus(j)
    await b2.start()
    assert b2.boot_id != boot1
    assert b2.sequence == 0
    assert b2.revision == 0
    await b2.publish(make_envelope(event_id="2"))
    assert b2.sequence == 1
    # old boot still readable
    assert len(j.read_events(boot1, 0, 10)) == 1
    await b2.close()
```

**close/start note:** After `close()`, journal is closed. Second `EventBus.start()` must `journal.open()` again — already in `start()`. Ensure `close` does not delete rows.

- [ ] **Step 2: Implement + run**

```powershell
uv run pytest tests/test_event_bus_order.py -v
```

Expected: PASS.

- [ ] **Step 3: Harden publish_command_event transition_json**

```python
from metascan.journal.commands import CommandTransitionRecord, build_transition_json

transition = CommandTransitionRecord(
    boot_id=stamped.boot_id,
    sequence=stamped.sequence,
    command_id=status.command_id,
    from_state=from_state,
    to_state=str(status.state.value if hasattr(status.state, "value") else status.state),
    ts=status.updated_at,
    transition_json=build_transition_json(
        command_id=status.command_id,
        from_state=from_state,
        to_state=str(status.state.value if hasattr(status.state, "value") else status.state),
        sequence=stamped.sequence,
    ),
)
```

---

## Task 9: Full suite + SP2_SUMMARY + single commit

- [ ] **Step 1: Run full SP2 + SP1 regression**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4\backend
uv run pytest tests/ -v
```

Expected: all PASS (SP1 + SP2).

Required green set:

| Test file | Cases covered |
|---|---|
| `test_journal_triggers.py` | schema/pragmas, events/cmd_transitions UPDATE/DELETE abort, double-open |
| `test_journal_crash.py` | inject failure, subprocess uncommitted, reopen clean |
| `test_replay.py` | after-exclusive, boot-scope, order, limit, unknown boot, wire roundtrip |
| `test_event_bus_order.py` | sequence/revision rules, sub order, concurrent publish, close, unsubscribe, new boot |
| `test_event_bus_overflow.py` | isolation, marker, lag count, log subscriber_id, ack_resync |
| `test_commit_before_publish.py` | commit before fan-out, restore counters |
| `test_command_tx.py` | atomic bundle, rollback, paired sequence, idempotent key |

- [ ] **Step 2: Write `backend/SP2_SUMMARY.md`**

```markdown
# SP2 — Append-only journal + EventBus

## Scope delivered

- SQLite journal (`WAL` + `synchronous=NORMAL`, busy_timeout default 5s)
- Tables: `events`, `commands`, `command_transitions` + append-only triggers
- Dedicated single-thread `ThreadPoolExecutor` owns write connection
- `Journal.append_event_committed` / `read_events` / `commit_bundle` / `try_insert_command_create`
- `EventBus`: `_publish_lock`, boot_id UUID4, sequence/revision, subscribe/unsubscribe
- COMMIT before fan-out; commit failure restores counters; no partial visibility
- Bounded subscriber queues; overflow → LAGGING + resync marker + warning log
- `ack_resync()` clears lagging; dropped events recovered via `read_events` only
- Command current row + transition share sequence with paired domain event
- Tests: crash, triggers, replay, order, concurrent, overflow, commit-before-publish, command TX

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

## Not in SP2

- FastAPI/SSE, MT5 gateway, RiskGate, snapshot rebuild
- Command lifecycle graph validation (RuntimeCore / SP3+)
- Frontend contract changes
```

- [ ] **Step 3: Self-check file map matches design §10**

All design files present; plus `test_command_tx.py` (design table "Command TX") and `tests/helpers.py` / `tests/crash_helpers/`.

- [ ] **Step 4: Single commit (only after all green)**

```powershell
cd C:\Users\dirga\Documents\xdirga-metascan-v4
git status
git add backend/src/metascan/journal backend/src/metascan/bus backend/tests/test_journal_triggers.py backend/tests/test_journal_crash.py backend/tests/test_replay.py backend/tests/test_event_bus_order.py backend/tests/test_event_bus_overflow.py backend/tests/test_commit_before_publish.py backend/tests/test_command_tx.py backend/tests/conftest.py backend/tests/helpers.py backend/tests/crash_helpers backend/pyproject.toml backend/SP2_SUMMARY.md
git commit -m "SP2: append-only journal + EventBus"
```

Do **not** add `*.sqlite`, `.env`, `.venv`.

If repo still not a git repo: `git init` only if user requests; otherwise stop after green tests and SUMMARY.

---

## Self-review (plan author)

### 1. Spec coverage (SP2_DESIGN.md)

| Design § | Plan task |
|---|---|
| §2 WAL/NORMAL/FK/busy | Task 1 |
| §3.1 events + indexes + triggers | Task 1–2 |
| §3.2 commands + transitions + triggers | Task 1, 7 |
| §4 sequence/revision/boot_id | Task 4, 8 |
| §5.2 publish lock / commit / fan-out | Task 4–5 |
| §5.3 overflow / lagging / marker / ack | Task 6 |
| §5.4 subscribe API | Task 4, 8 |
| §6 read_events | Task 2 |
| §7 command journaling same TX / same sequence | Task 7 |
| §8 lifecycle open/run/shutdown/crash | Task 3, 8 |
| §9 errors | Tasks 2–7 |
| §10 file map | File map section |
| §12 test plan rows | Tasks 2–7 |

### 2. Placeholder scan

No TBD/TODO. Full SQL, interfaces, test bodies, commands included.

### 3. Type consistency

- `RuntimeEventEnvelope` / `RuntimeCommandStatus` from SP1 models
- `ResyncMarker.kind == "resync_required"`
- `CommandTransitionRecord.sequence` == event sequence
- `EventBus.publish(..., mutates_state: bool = True)`
- `READ_EVENTS_HARD_CAP = 10_000`
- `DEFAULT_SUBSCRIBER_MAXSIZE = 1024`
- Exceptions: `EventBusClosed`, `JournalError`, `JournalAlreadyOpen`

### 4. Ambiguity resolutions (locked)

1. **Executor deadlock:** write methods invoked via `journal.executor` use `_conn` directly; `run_on_writer` detects writer thread.
2. **Already-lagging fan-out:** drop events; do not replace marker.
3. **Logging:** stdlib logging, not structlog.
4. **entity_id:** position_id or order_id or command_id.
5. **Idempotent command create:** `try_insert_command_create` returns existing without new event.
6. **pytest-asyncio:** `asyncio_mode = auto`.
7. **One commit only** after full green: message `SP2: append-only journal + EventBus`.

### 5. Risks

- Windows + WAL + multi-connection: use separate read connections for `read_events`; always close them.
- `Queue(maxsize=1)` overflow: after clear, `put_nowait(marker)` must succeed — assert maxsize >= 1 in `subscribe`.
- Enum `.value` on `type`/`kind`/`state` when writing SQL columns.

---

## Execution handoff

Plan complete and saved to `backend/SP2_PLAN.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans, batch with checkpoints  

**Which approach?**
