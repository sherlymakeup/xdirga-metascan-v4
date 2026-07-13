from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.contract.models import RuntimeCommandStatus
from metascan.journal.commands import CommandTransitionRecord, IdempotencyConflict
from metascan.journal.db import Journal


def _status(command_id: str = "c1", key: str = "key") -> RuntimeCommandStatus:
    return RuntimeCommandStatus(
        command_id=command_id,
        client_request_id="client",
        correlation_id="corr",
        idempotency_key=key,
        kind="position.close",
        state="PREPARED",
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:00Z",
    )


def _transition(command_id: str = "c1") -> CommandTransitionRecord:
    return CommandTransitionRecord("boot", 1, command_id, None, "PREPARED", "2026-07-13T00:00:00Z", "{}")


def test_commands_schema_uses_origin_xor_records_and_execution_kind(journal_path: Path) -> None:
    journal = Journal(journal_path)
    journal.open()
    try:
        def check(conn: sqlite3.Connection) -> None:
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='commands'").fetchone()[0]
            assert "execution_kind" in sql
            assert "internal_record_json" in sql
            assert "CHECK" in sql
            assert "record_json        TEXT    NULL" in sql

        journal.run_on_writer(check)
    finally:
        journal.close()


def test_global_idempotency_compares_canonical_request_without_writes(journal_path: Path) -> None:
    journal = Journal(journal_path)
    journal.open()
    try:
        first = _status()
        envelope = make_envelope(boot_id="boot", sequence=1, revision=1, command_id="c1")
        assert journal.try_insert_command_create(first, _transition(), envelope, '{"kind":"position.close"}')[1]
        replay, created = journal.try_insert_command_create(
            _status("c2"), _transition("c2"), make_envelope(boot_id="boot", sequence=2, revision=2, command_id="c2"), '{"kind":"position.close"}'
        )
        assert not created
        assert replay.command_id == "c1"
        with pytest.raises(IdempotencyConflict):
            journal.try_insert_command_create(
                _status("c3"), _transition("c3"), make_envelope(boot_id="boot", sequence=3, revision=3, command_id="c3"), '{"kind":"position.close","target_id":"42"}'
            )
        assert journal.run_on_writer(lambda conn: conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]) == 1
        assert journal.run_on_writer(lambda conn: conn.execute("SELECT COUNT(*) FROM command_transitions").fetchone()[0]) == 1
    finally:
        journal.close()


def test_existing_commands_table_rebuild_preserves_transport_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE commands (command_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, client_request_id TEXT NOT NULL, correlation_id TEXT NOT NULL, kind TEXT NOT NULL, target_id TEXT, state TEXT NOT NULL, progress REAL, current_step TEXT, message TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, record_json TEXT NOT NULL)""")
    conn.execute("INSERT INTO commands VALUES ('legacy','idem','client','corr','position.close',NULL,'PREPARED',NULL,NULL,NULL,NULL,'t','t','{}')")
    conn.commit()
    conn.close()
    journal = Journal(path)
    journal.open()
    try:
        row = journal.run_on_writer(lambda c: c.execute("SELECT origin, request_json, record_json, internal_record_json, execution_kind FROM commands WHERE command_id='legacy'").fetchone())
        assert tuple(row) == ("TRANSPORT", "{}", "{}", None, None)
    finally:
        journal.close()


def test_entry_intent_is_durable_and_recovers_unresolved(journal_path: Path) -> None:
    journal = Journal(journal_path)
    journal.open()
    try:
        journal.register_entry_intent(symbol="XAUUSDm", command_id="entry-1", state="PENDING", order_ticket=7)
    finally:
        journal.close()
    reopened = Journal(journal_path)
    reopened.open()
    try:
        assert reopened.recover_entry_intents() == [{"symbol": "XAUUSDm", "command_id": "entry-1", "state": "PENDING", "order_ticket": 7, "deal_ticket": None, "position_ticket": None}]
        reopened.update_entry_intent("XAUUSDm", state="RESOLVED", position_ticket=11)
        assert reopened.recover_entry_intents() == []
        reopened.clear_entry_intent("XAUUSDm")
    finally:
        reopened.close()
