from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope

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

    @property
    def executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            raise JournalError("journal not open")
        return self._executor

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

        if threading.current_thread().name.startswith("journal-writer"):
            return _call()
        return self._executor.submit(_call).result()

    def append_event_committed(self, envelope: RuntimeEventEnvelope) -> None:
        if not self._open or self._conn is None:
            raise JournalError("journal not open")
        from metascan.journal import events as events_mod

        def _do(conn: sqlite3.Connection) -> None:
            events_mod.append_event_committed(conn, envelope)

        if threading.current_thread().name.startswith("journal-writer"):
            _do(self._conn)
        else:
            self.run_on_writer(_do)

    def read_events(
        self, boot_id: str, after_sequence: int, limit: int
    ) -> list[RuntimeEventEnvelope]:
        from metascan.journal import events as events_mod

        return events_mod.read_events(
            str(self._path),
            boot_id,
            after_sequence,
            limit,
            busy_timeout_ms=self._busy_timeout_ms,
        )

    def commit_bundle(
        self,
        *,
        envelope: RuntimeEventEnvelope | None = None,
        command_upsert: RuntimeCommandStatus | None = None,
        transition: object | None = None,
    ) -> None:
        if not self._open or self._conn is None:
            raise JournalError("journal not open")
        from metascan.journal import commands as cmd_mod
        from metascan.journal import events as events_mod
        from metascan.journal.commands import CommandTransitionRecord

        if command_upsert is not None or transition is not None:
            if envelope is None:
                raise JournalError(
                    "envelope required with command/transition (SP2 atomicity)"
                )
            if command_upsert is None or transition is None:
                raise JournalError(
                    "command_upsert and transition required together with envelope"
                )
            if not isinstance(transition, CommandTransitionRecord):
                raise JournalError("invalid transition type")

        def _do(conn: sqlite3.Connection) -> None:
            try:
                if envelope is not None:
                    events_mod.insert_event(conn, envelope)
                if command_upsert is not None:
                    assert isinstance(transition, CommandTransitionRecord)
                    cmd_mod.upsert_command_and_transition(
                        conn, command_upsert, transition
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

        if threading.current_thread().name.startswith("journal-writer"):
            _do(self._conn)
        else:
            self.run_on_writer(_do)

    def try_insert_command_create(
        self,
        status: RuntimeCommandStatus,
        transition: object,
        envelope: RuntimeEventEnvelope,
    ) -> tuple[RuntimeCommandStatus, bool]:
        from metascan.journal.commands import (
            CommandTransitionRecord,
            get_command_by_idempotency_key,
            upsert_command_and_transition,
        )
        from metascan.journal import events as events_mod

        if not isinstance(transition, CommandTransitionRecord):
            raise JournalError("invalid transition type")

        def _body(conn: sqlite3.Connection) -> tuple[RuntimeCommandStatus, bool]:
            try:
                existing = get_command_by_idempotency_key(
                    conn, status.idempotency_key
                )
                if existing is not None:
                    return existing, False
                events_mod.insert_event(conn, envelope)
                upsert_command_and_transition(conn, status, transition)
                conn.commit()
                return status, True
            except BaseException:
                conn.rollback()
                raise

        return self.run_on_writer(_body)
