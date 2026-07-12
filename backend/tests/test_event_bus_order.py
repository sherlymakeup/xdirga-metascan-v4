from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import make_envelope
from metascan.bus.event_bus import EventBus, EventBusClosed
from metascan.journal.db import Journal


@pytest.fixture
async def bus(journal_path: Path):
    j = Journal(journal_path)
    b = EventBus(j)
    await b.start()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_publish_stamps_monotonic_sequence_and_revision(bus: EventBus) -> None:
    assert bus.sequence == 0
    assert bus.revision == 0
    boot = bus.boot_id
    assert boot

    e1 = await bus.publish(make_envelope(event_id="a"), mutates_state=True)
    assert e1.boot_id == boot
    assert e1.sequence == 1
    assert e1.revision == 1
    assert bus.sequence == 1
    assert bus.revision == 1

    e2 = await bus.publish(make_envelope(event_id="b"), mutates_state=False)
    assert e2.sequence == 2
    assert e2.revision == 1
    assert bus.revision == 1

    e3 = await bus.publish(make_envelope(event_id="c"), mutates_state=True)
    assert e3.sequence == 3
    assert e3.revision == 2


@pytest.mark.asyncio
async def test_subscriber_receives_in_sequence_order(bus: EventBus) -> None:
    sub = await bus.subscribe("s1")
    for i in range(5):
        await bus.publish(make_envelope(event_id=f"e{i}"))
    seqs = []
    for _ in range(5):
        item = await sub.get()
        seqs.append(item.sequence)  # type: ignore[union-attr]
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_concurrent_publish_unique_monotonic(bus: EventBus) -> None:
    n = 50

    async def one(i: int):
        return await bus.publish(make_envelope(event_id=f"c{i}"))

    results = await asyncio.gather(*[one(i) for i in range(n)])
    seqs = sorted(r.sequence for r in results)
    assert seqs == list(range(1, n + 1))
    assert len({r.sequence for r in results}) == n
    stored = bus.journal.read_events(bus.boot_id, 0, n)
    assert [e.sequence for e in stored] == list(range(1, n + 1))


@pytest.mark.asyncio
async def test_publish_after_close_raises(bus: EventBus) -> None:
    await bus.close()
    with pytest.raises(EventBusClosed):
        await bus.publish(make_envelope())


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    sub = await bus.subscribe("s1")
    await bus.unsubscribe("s1")
    await bus.publish(make_envelope(event_id="z"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_close_wakes_blocked_subscriber(bus: EventBus) -> None:
    from metascan.bus.event_bus import CLOSED_KIND, ClosedMarker

    sub = await bus.subscribe("waiter")
    waiter = asyncio.create_task(sub.get())
    await asyncio.sleep(0)  # let waiter block on empty queue
    assert not waiter.done()
    await bus.close()
    item = await asyncio.wait_for(waiter, timeout=0.5)
    assert isinstance(item, ClosedMarker)
    assert item.kind == CLOSED_KIND
    assert item.subscriber_id == "waiter"


@pytest.mark.asyncio
async def test_new_boot_resets_counters(journal_path: Path) -> None:
    j = Journal(journal_path)
    b1 = EventBus(j)
    await b1.start()
    boot1 = b1.boot_id
    await b1.publish(make_envelope(event_id="1"))
    assert b1.sequence == 1
    await b1.close()

    b2 = EventBus(j)
    await b2.start()
    assert b2.boot_id != boot1
    assert b2.sequence == 0
    assert b2.revision == 0
    await b2.publish(make_envelope(event_id="2"))
    assert b2.sequence == 1
    assert len(j.read_events(boot1, 0, 10)) == 1
    await b2.close()
