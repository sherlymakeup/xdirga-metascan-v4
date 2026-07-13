from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.pipeline.request import InternalCommandRecord

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
        self._migrate_commands(conn, schema)
        conn.executescript(schema)
        conn.commit()
        return conn

    @staticmethod
    def _migrate_commands(conn: sqlite3.Connection, schema: str) -> None:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='commands'").fetchone()
        if exists is None:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(commands)")}
        required = {"request_json", "origin", "execution_kind", "record_json", "internal_record_json"}
        if required.issubset(columns):
            return
        conn.execute("ALTER TABLE commands RENAME TO commands_legacy_sp5")
        start = schema.index("CREATE TABLE IF NOT EXISTS commands")
        end = schema.index("CREATE TABLE IF NOT EXISTS command_transitions")
        conn.executescript(schema[start:end])
        legacy_columns = {row[1] for row in conn.execute("PRAGMA table_info(commands_legacy_sp5)")}
        request_json = "request_json" if "request_json" in legacy_columns else "'{}'"
        origin = "origin" if "origin" in legacy_columns else "'TRANSPORT'"
        conn.execute(
            f"""
            INSERT INTO commands (
              command_id, idempotency_key, client_request_id, correlation_id, kind, target_id,
              state, progress, current_step, message, error_code, created_at, updated_at,
              request_json, origin, execution_kind, record_json, internal_record_json
            )
            SELECT command_id, idempotency_key, client_request_id, correlation_id, kind, target_id,
              state, progress, current_step, message, error_code, created_at, updated_at,
              {request_json}, {origin}, NULL, record_json, NULL
            FROM commands_legacy_sp5
            """
        )
        conn.execute("DROP TABLE commands_legacy_sp5")

    def register_entry_intent(self, *, symbol: str, command_id: str, state: str, order_ticket: int | None = None, deal_ticket: int | None = None, position_ticket: int | None = None) -> None:
        self.run_on_writer(lambda conn: (conn.execute("INSERT INTO entry_intents (symbol, command_id, state, order_ticket, deal_ticket, position_ticket) VALUES (?, ?, ?, ?, ?, ?)", (symbol, command_id, state, order_ticket, deal_ticket, position_ticket)), conn.commit()))

    def update_entry_intent(self, symbol: str, *, state: str, order_ticket: int | None = None, deal_ticket: int | None = None, position_ticket: int | None = None) -> None:
        self.run_on_writer(lambda conn: (conn.execute("UPDATE entry_intents SET state=?, order_ticket=COALESCE(?, order_ticket), deal_ticket=COALESCE(?, deal_ticket), position_ticket=COALESCE(?, position_ticket) WHERE symbol=?", (state, order_ticket, deal_ticket, position_ticket, symbol)), conn.commit()))

    def clear_entry_intent(self, symbol: str) -> None:
        self.run_on_writer(lambda conn: (conn.execute("DELETE FROM entry_intents WHERE symbol=?", (symbol,)), conn.commit()))

    def recover_entry_intents(self) -> list[dict[str, object]]:
        def fetch(conn: sqlite3.Connection) -> list[dict[str, object]]:
            rows = conn.execute("SELECT symbol, command_id, state, order_ticket, deal_ticket, position_ticket FROM entry_intents WHERE state NOT IN ('RESOLVED', 'CLEARED') ORDER BY symbol").fetchall()
            return [dict(row) for row in rows]
        return self.run_on_writer(fetch)

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

    def commit_internal_bundle(
        self,
        *,
        envelope: RuntimeEventEnvelope,
        record: InternalCommandRecord,
        transition: object,
        internal_record_json: str,
    ) -> None:
        if not self._open or self._conn is None:
            raise JournalError("journal not open")
        from metascan.journal import commands as cmd_mod
        from metascan.journal import events as events_mod
        from metascan.journal.commands import CommandTransitionRecord
        if not isinstance(transition, CommandTransitionRecord):
            raise JournalError("invalid transition type")

        def _do(conn: sqlite3.Connection) -> None:
            try:
                events_mod.insert_event(conn, envelope)
                cmd_mod.upsert_internal_command_and_transition(
                    conn, record, transition, internal_record_json
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
        status: RuntimeCommandStatus | InternalCommandRecord,
        transition: object,
        envelope: RuntimeEventEnvelope,
        request_json: str = "{}",
        *,
        origin: str = "TRANSPORT",
        execution_kind: str | None = None,
        internal_record_json: str | None = None,
    ) -> tuple[RuntimeCommandStatus, bool]:
        from metascan.journal.commands import (
            CommandTransitionRecord,
            IdempotencyConflict,
            get_command_by_idempotency_key,
            upsert_command_and_transition,
        )
        from metascan.journal import events as events_mod

        if not isinstance(transition, CommandTransitionRecord):
            raise JournalError("invalid transition type")

        def _body(conn: sqlite3.Connection) -> tuple[RuntimeCommandStatus, bool]:
            try:
                existing = get_command_by_idempotency_key(conn, status.idempotency_key)
                if existing is not None:
                    row = conn.execute("SELECT request_json FROM commands WHERE idempotency_key = ?", (status.idempotency_key,)).fetchone()
                    if row is None or str(row[0]) != request_json:
                        raise IdempotencyConflict("idempotency key reused with different request")
                    return existing, False
                events_mod.insert_event(conn, envelope)
                if origin == "TRANSPORT" and request_json == "{}":
                    upsert_command_and_transition(conn, status, transition)
                else:
                    upsert_command_and_transition(
                        conn,
                        status,
                        transition,
                        request_json=request_json,
                        origin=origin,
                        execution_kind=execution_kind,
                        internal_record_json=internal_record_json,
                    )
                conn.commit()
                return status, True
            except BaseException:
                conn.rollback()
                raise

        return self.run_on_writer(_body)
