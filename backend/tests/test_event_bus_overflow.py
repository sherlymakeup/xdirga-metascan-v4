from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import RESYNC_KIND, EventBus, ResyncMarker
from metascan.journal.db import Journal


@pytest.mark.asyncio
async def test_slow_subscriber_overflow_isolates_fast(
    journal_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=2)
    await bus.start()
    slow = await bus.subscribe("slow", maxsize=2)
    fast = await bus.subscribe("fast", maxsize=64)

    with caplog.at_level(logging.WARNING, logger="metascan.bus"):
        await bus.publish(make_envelope(event_id="1"))
        await bus.publish(make_envelope(event_id="2"))
        await bus.publish(make_envelope(event_id="3"))
        await bus.publish(make_envelope(event_id="4"))
        await bus.publish(make_envelope(event_id="5"))

    fast_ids = []
    for _ in range(5):
        item = await asyncio.wait_for(fast.get(), timeout=1)
        assert not isinstance(item, ResyncMarker)
        fast_ids.append(item.event_id)
    assert fast_ids == ["1", "2", "3", "4", "5"]

    assert bus.lagging_subscriber_count == 1
    assert slow.is_lagging is True

    marker = await asyncio.wait_for(slow.get(), timeout=1)
    assert isinstance(marker, ResyncMarker)
    assert marker.kind == RESYNC_KIND
    assert marker.reason == "subscriber_overflow"
    assert marker.subscriber_id == "slow"
    assert marker.boot_id == bus.boot_id
    assert marker.last_committed_sequence >= 3
    assert slow._queue_ref().empty()  # noqa: SLF001

    assert any(
        "subscriber_overflow" in r.message or r.msg == "subscriber_overflow"
        for r in caplog.records
    )
    assert any(
        getattr(r, "subscriber_id", None) == "slow" or "slow" in r.getMessage()
        for r in caplog.records
    )

    slow.ack_resync()
    assert slow.is_lagging is False
    assert bus.lagging_subscriber_count == 0

    await bus.publish(make_envelope(event_id="6"))
    item = await asyncio.wait_for(slow.get(), timeout=1)
    assert not isinstance(item, ResyncMarker)
    assert item.event_id == "6"

    await bus.close()


@pytest.mark.asyncio
async def test_overflow_resync_marker_always_enqueued(journal_path: Path) -> None:
    """After drain, resync marker must land; never silent drop."""
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=1)
    await bus.start()
    sub = await bus.subscribe("s", maxsize=1)
    await bus.publish(make_envelope(event_id="a"))
    await bus.publish(make_envelope(event_id="b"))  # overflow
    assert sub.is_lagging
    m = await asyncio.wait_for(sub.get(), timeout=1)
    assert isinstance(m, ResyncMarker)
    assert m.kind == RESYNC_KIND
    assert m.subscriber_id == "s"
    await bus.close()


@pytest.mark.asyncio
async def test_lagging_drops_until_ack(journal_path: Path) -> None:
    j = Journal(journal_path)
    bus = EventBus(j, default_queue_maxsize=1)
    await bus.start()
    sub = await bus.subscribe("s", maxsize=1)
    await bus.publish(make_envelope(event_id="a"))
    await bus.publish(make_envelope(event_id="b"))
    assert sub.is_lagging
    await bus.publish(make_envelope(event_id="c"))
    m = await sub.get()
    assert isinstance(m, ResyncMarker)
    await bus.publish(make_envelope(event_id="d"))
    assert sub._queue_ref().empty()  # noqa: SLF001
    sub.ack_resync()
    await bus.publish(make_envelope(event_id="e"))
    got = await sub.get()
    assert got.event_id == "e"  # type: ignore[union-attr]
    await bus.close()
