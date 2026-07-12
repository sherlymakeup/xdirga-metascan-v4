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
    state = status.state.value if hasattr(status.state, "value") else str(status.state)
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
            state,
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
