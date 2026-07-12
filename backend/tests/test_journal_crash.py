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
    """Hard-kill child mid-tx (no rollback/commit/close). Uncommitted INSERT must vanish."""
    j = Journal(journal_path)
    j.open()
    j.close()
    assert journal_path.is_file()

    script = Path(__file__).parent / "crash_helpers" / "interrupt_insert.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(journal_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 42, (
        f"expected hard exit 42, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )

    # Optional WAL recovery surface before Journal open
    ck = sqlite3.connect(journal_path)
    try:
        ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        ck.close()

    j2 = Journal(journal_path)
    j2.open()
    try:
        assert j2.read_events("crash-boot", 0, 10) == []

        def raw_count(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE boot_id = ?",
                    ("crash-boot",),
                ).fetchone()[0]
            )

        assert j2.run_on_writer(raw_count) == 0

        env = make_envelope(boot_id="new-boot", sequence=1, revision=1, event_id="ok")
        j2.append_event_committed(env)
        assert len(j2.read_events("new-boot", 0, 10)) == 1
        assert j2.read_events("crash-boot", 0, 10) == []
    finally:
        j2.close()


def test_append_commit_failure_rolls_back(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        import metascan.journal.events as ev

        real_insert = ev.insert_event

        def bad_insert(conn: sqlite3.Connection, envelope: object) -> None:
            real_insert(conn, envelope)  # type: ignore[arg-type]
            raise sqlite3.DatabaseError("disk full")

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
