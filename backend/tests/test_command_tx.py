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
    row = j.run_on_writer(
        lambda c: get_command_by_idempotency_key(c, st.idempotency_key)
    )
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
        env = make_envelope(
            boot_id="b", sequence=1, revision=1, command_id=st.command_id
        )
        created, is_new = j.try_insert_command_create(st, tr, env)
        assert is_new is True
        assert created.command_id == st.command_id
        again, is_new2 = j.try_insert_command_create(st, tr, env)
        assert is_new2 is False
        assert again.command_id == st.command_id

        def n(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute("SELECT COUNT(*) FROM command_transitions").fetchone()[0]
            )

        assert j.run_on_writer(n) == 1
    finally:
        j.close()


def test_try_insert_failure_rolls_back_and_writer_recovers(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        env = make_envelope(
            boot_id="b", sequence=1, revision=1, command_id=st.command_id
        )
        import metascan.journal.commands as cmd_mod

        real = cmd_mod.upsert_command_and_transition

        def boom(conn, status, transition):  # type: ignore[no-untyped-def]
            real(conn, status, transition)
            raise RuntimeError("fail after upsert")

        monkeypatch.setattr(cmd_mod, "upsert_command_and_transition", boom)
        with pytest.raises(RuntimeError, match="fail after upsert"):
            j.try_insert_command_create(st, tr, env)

        assert j.read_events("b", 0, 10) == []
        assert (
            j.run_on_writer(lambda c: get_command_by_idempotency_key(c, "idem-1"))
            is None
        )

        def counts(conn: sqlite3.Connection) -> tuple[int, int]:
            e = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            t = int(
                conn.execute("SELECT COUNT(*) FROM command_transitions").fetchone()[0]
            )
            return e, t

        assert j.run_on_writer(counts) == (0, 0)

        # writer recovers: later append + reopen clean
        ok = make_envelope(boot_id="b2", sequence=1, revision=1, event_id="ok")
        j.append_event_committed(ok)
        assert len(j.read_events("b2", 0, 10)) == 1
        j.close()

        j2 = Journal(journal_path)
        j2.open()
        try:
            assert j2.read_events("b", 0, 10) == []
            assert len(j2.read_events("b2", 0, 10)) == 1
            assert (
                j2.run_on_writer(lambda c: get_command_by_idempotency_key(c, "idem-1"))
                is None
            )
        finally:
            j2.close()
    finally:
        if j.is_open:
            j.close()


def test_commit_bundle_requires_envelope_with_command(journal_path: Path) -> None:
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
        with pytest.raises(Exception, match="envelope"):
            j.commit_bundle(command_upsert=st, transition=tr)
        assert (
            j.run_on_writer(lambda c: get_command_by_idempotency_key(c, "idem-1"))
            is None
        )
    finally:
        j.close()
