from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from metascan.contract.models import RuntimeCommandStatus
from metascan.pipeline.request import InternalCommandRecord


@dataclass(frozen=True, slots=True)
class CommandTransitionRecord:
    boot_id: str
    sequence: int
    command_id: str
    from_state: str | None
    to_state: str
    ts: str
    transition_json: str


class IdempotencyConflict(RuntimeError):
    pass


def get_command_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> RuntimeCommandStatus | InternalCommandRecord | None:
    row = conn.execute(
        "SELECT * FROM commands WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    if row["origin"] == "INTERNAL":
        return InternalCommandRecord.from_row(row)
    return RuntimeCommandStatus.model_validate_json(row["record_json"])


def get_command_request_json(conn: sqlite3.Connection, command_id: str) -> str | None:
    row = conn.execute("SELECT request_json FROM commands WHERE command_id = ?", (command_id,)).fetchone()
    return None if row is None else str(row[0])


def upsert_command_and_transition(
    conn: sqlite3.Connection,
    status: RuntimeCommandStatus | InternalCommandRecord,
    transition: CommandTransitionRecord,
    *,
    request_json: str | None = None,
    origin: str | None = None,
    execution_kind: str | None = None,
    internal_record_json: str | None = None,
) -> None:
    origin = origin or ("INTERNAL" if isinstance(status, InternalCommandRecord) else "TRANSPORT")
    if isinstance(status, InternalCommandRecord):
        execution_kind = execution_kind or status.execution_kind
        internal_record_json = internal_record_json or status.internal_json()
    record_json = status.model_dump_json() if origin == "TRANSPORT" else None
    if origin == "INTERNAL" and isinstance(status, RuntimeCommandStatus):
        raise ValueError("internal commands require InternalCommandRecord")
    if origin == "TRANSPORT" and not isinstance(status, RuntimeCommandStatus):
        raise ValueError("transport commands require RuntimeCommandStatus")
    if origin == "INTERNAL" and (execution_kind is None or internal_record_json is None):
        raise ValueError("internal commands require execution_kind and internal_record_json")
    if origin == "TRANSPORT" and (execution_kind is not None or internal_record_json is not None):
        raise ValueError("transport commands cannot persist internal execution identity")
    kind = status.kind.value if hasattr(status.kind, "value") else str(status.kind)
    state = status.state.value if hasattr(status.state, "value") else str(status.state)
    conn.execute(
        """
        INSERT INTO commands (
          command_id, idempotency_key, client_request_id, correlation_id,
          kind, target_id, state, progress, current_step, message, error_code,
          created_at, updated_at, request_json, origin, execution_kind, record_json, internal_record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(command_id) DO UPDATE SET
            state=excluded.state,
            progress=excluded.progress,
            current_step=excluded.current_step,
            message=excluded.message,
            error_code=excluded.error_code,
            updated_at=excluded.updated_at,
            record_json=excluded.record_json,
            internal_record_json=excluded.internal_record_json
        """,
        (
            status.command_id,
            status.idempotency_key,
            status.client_request_id,
            status.correlation_id,
            kind,
            status.target_id,
            state,
            status.progress,
            status.current_step,
            status.message,
            status.error_code,
            status.created_at,
            status.updated_at,
            request_json if request_json is not None else "{}",
            origin,
            execution_kind,
            record_json,
            internal_record_json,
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


def upsert_internal_command_and_transition(
    conn: sqlite3.Connection,
    record: InternalCommandRecord,
    transition: CommandTransitionRecord,
    internal_record_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO commands (
          command_id, idempotency_key, client_request_id, correlation_id,
          kind, target_id, state, progress, current_step, message, error_code,
          created_at, updated_at, request_json, origin, execution_kind, record_json, internal_record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'INTERNAL', 'INTERNAL_ENTRY_MARKET', NULL, ?)
        ON CONFLICT(command_id) DO UPDATE SET
            state=excluded.state,
            progress=excluded.progress,
            current_step=excluded.current_step,
            message=excluded.message,
            error_code=excluded.error_code,
            updated_at=excluded.updated_at,
            internal_record_json=excluded.internal_record_json
        """,
        (
            record.command_id,
            record.idempotency_key,
            record.client_request_id,
            record.correlation_id,
            record.kind,
            record.target_id,
            record.state,
            record.progress,
            record.current_step,
            record.message,
            record.error_code,
            record.created_at,
            record.updated_at,
            internal_record_json,
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
