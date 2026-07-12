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
    except BaseException:
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
