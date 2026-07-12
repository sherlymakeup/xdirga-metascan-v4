"""Child: BEGIN IMMEDIATE + INSERT full event row, then hard-exit without COMMIT.

Windows-compatible abrupt termination via os._exit (no finally/cleanup/close).
Proves uncommitted journal rows do not become visible after reopen.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Full wire-shaped envelope JSON (valid if it had been committed).
_ENVELOPE_JSON = (
    '{"eventId":"crash-e1","type":"command.created","runtimeId":"rt1",'
    '"bootId":"crash-boot","revision":1,"sequence":1,'
    '"occurredAt":"2026-07-13T00:00:00Z","emittedAt":"2026-07-13T00:00:00Z",'
    '"receivedAt":"2026-07-13T00:00:00Z","severity":"INFO",'
    '"source":"LOCAL_RUNTIME","payload":{}}'
)


def main() -> None:
    db = Path(sys.argv[1])
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO events (boot_id, sequence, type, entity_id, ts, envelope_json)
        VALUES ('crash-boot', 1, 'command.created', NULL, '2026-07-13T00:00:00Z', ?)
        """,
        (_ENVELOPE_JSON,),
    )
    # Force page write into WAL buffer without COMMIT, then die.
    # No rollback, no commit, no close, no finally.
    conn.execute("SELECT 1 FROM events WHERE boot_id = 'crash-boot'").fetchone()
    os._exit(42)


if __name__ == "__main__":
    main()
