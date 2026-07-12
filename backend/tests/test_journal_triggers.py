from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.journal.db import Journal


def test_open_applies_schema_and_pragmas(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        def _check(conn: sqlite3.Connection) -> None:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            assert int(sync) == 1  # NORMAL
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "events" in tables
            assert "commands" in tables
            assert "command_transitions" in tables

        j.run_on_writer(_check)
    finally:
        j.close()


def test_events_update_forbidden(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = make_envelope(boot_id="b1", sequence=1, revision=1)

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
        env = make_envelope(boot_id="b1", sequence=1, revision=1)

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
