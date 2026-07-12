from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal


@pytest.mark.asyncio
async def test_no_fanout_until_commit_returns(journal_path: Path) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=16)
    await bus.start()
    sub = await bus.subscribe("s1")
    order: list[str] = []

    real_append = j.append_event_committed

    def tracked_append(envelope):  # type: ignore[no-untyped-def]
        order.append("commit_start")
        real_append(envelope)
        order.append("commit_done")

    with patch.object(j, "append_event_committed", side_effect=tracked_append):
        task = asyncio.create_task(bus.publish(make_envelope(event_id="e1")))
        await task
        order.append("after_publish")
        item = await asyncio.wait_for(sub.get(), timeout=1)
        order.append("got_item")
        assert item.sequence == 1  # type: ignore[union-attr]

    assert order.index("commit_done") < order.index("got_item")
    await bus.close()


@pytest.mark.asyncio
async def test_commit_failure_restores_counters_and_no_fanout(
    journal_path: Path,
) -> None:
    j = Journal(journal_path)
    bus = EventBus(j)
    await bus.start()
    sub = await bus.subscribe("s1", maxsize=8)

    def boom(envelope):  # type: ignore[no-untyped-def]
        raise RuntimeError("commit failed")

    with patch.object(j, "append_event_committed", side_effect=boom):
        with pytest.raises(RuntimeError, match="commit failed"):
            await bus.publish(make_envelope(event_id="x"))

    assert bus.sequence == 0
    assert bus.revision == 0
    assert sub._queue_ref().empty()  # noqa: SLF001
    ok = await bus.publish(make_envelope(event_id="y"))
    assert ok.sequence == 1
    assert bus.sequence == 1
    got = await sub.get()
    assert got.event_id == "y"  # type: ignore[union-attr]
    await bus.close()
