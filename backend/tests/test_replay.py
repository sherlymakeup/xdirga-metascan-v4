from __future__ import annotations

from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.journal.db import READ_EVENTS_HARD_CAP, Journal


def test_read_events_after_exclusive_ordered_bounded(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        for seq in (1, 2, 3):
            env = make_envelope(
                event_id=f"e{seq}",
                boot_id="bootA",
                sequence=seq,
                revision=seq,
            )
            j.append_event_committed(env)
        j.append_event_committed(
            make_envelope(event_id="x", boot_id="bootB", sequence=1, revision=1)
        )
        got = j.read_events("bootA", after_sequence=1, limit=10)
        assert [e.sequence for e in got] == [2, 3]
        assert all(e.boot_id == "bootA" for e in got)
        assert got[0].event_id == "e2"
        assert j.read_events("bootA", after_sequence=3, limit=10) == []
        assert j.read_events("unknown", after_sequence=0, limit=10) == []
        limited = j.read_events("bootA", after_sequence=0, limit=2)
        assert [e.sequence for e in limited] == [1, 2]
    finally:
        j.close()


def test_read_events_limit_validation(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        with pytest.raises(ValueError):
            j.read_events("b", 0, 0)
        with pytest.raises(ValueError):
            j.read_events("b", 0, -1)
        with pytest.raises(ValueError):
            j.read_events("b", 0, READ_EVENTS_HARD_CAP + 1)
    finally:
        j.close()


def test_append_roundtrip_wire_json(journal_path: Path) -> None:
    j = Journal(journal_path)
    j.open()
    try:
        env = make_envelope(
            event_id="e9",
            boot_id="b",
            sequence=1,
            revision=1,
            command_id="cmd-1",
            payload={"k": 1},
        )
        j.append_event_committed(env)
        got = j.read_events("b", 0, 1)[0]
        assert got.event_id == "e9"
        assert got.command_id == "cmd-1"
        assert got.payload == {"k": 1}
        assert got.type.value == "command.created" or str(got.type) == "command.created"
    finally:
        j.close()
