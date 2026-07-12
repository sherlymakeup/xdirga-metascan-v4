from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info, event_type
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.pending_intent import NullPendingIntentLookup
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


class ClosePending:
    def __init__(self, tickets: set[int]) -> None:
        self.tickets = tickets

    def has_pending_close(self, ticket: int) -> bool:
        return ticket in self.tickets

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False

    def has_pending_modify(self, ticket: int) -> bool:
        return False


async def _boot_with_pos(tmp_path, pending=None):
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    fake.set_positions([{
        "ticket": 55, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.2,
        "price_open": 2300.0, "price_current": 2305.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 20.0, "swap": -0.5, "commission": -1.0, "type": 0,
        "time_msc": 0, "identifier": 55, "comment": "",
    }])
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(
        fake,
        config=GatewayConfig(
            login=1, password="p", server="s", symbol_suffix="m",
            watchlist_bases=("XAUUSD",), bot_magic=BOT, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", pending=pending or NullPendingIntentLookup(),
    )
    gw.start()
    gw.wait_boot(3.0)
    consumer.start()
    sub = await bus.subscribe("s1", maxsize=2048)
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if hasattr(e, "type") and event_type(e) == "position.opened":
            break
    return bus, gw, consumer, sub, fake


async def test_external_full_close_emits_position_and_trade_manual(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot_with_pos(tmp_path)
    fake.remove_position(55)
    seen = []
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if not hasattr(e, "type"):
            continue
        seen.append(event_type(e))
        if "trade.closed" in seen and "position.closed" in seen:
            break
    assert "position.closed" in seen
    assert "trade.closed" in seen
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    trade = next(r for r in rows if event_type(r) == "trade.closed")
    assert trade.payload["exitReason"] == "MANUAL"
    assert trade.payload["positionId"] == "55"
    assert trade.payload["netPnl"] == trade.payload["grossPnl"] + trade.payload["commission"] + trade.payload["swap"]
    assert "MANUAL_CLOSE" not in str(trade.payload)
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_pending_close_suppresses_external_trade_closed(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot_with_pos(tmp_path, pending=ClosePending({55}))
    fake.remove_position(55)
    seen = []
    await asyncio.sleep(0.5)
    end = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < end:
        try:
            e = await asyncio.wait_for(sub.get(), timeout=0.2)
        except asyncio.TimeoutError:
            break
        if hasattr(e, "type"):
            seen.append(event_type(e))
    assert "trade.closed" not in seen
    assert "position.closed" not in seen
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_same_sequence_different_pending_different_events(tmp_path: Path) -> None:
    from metascan.mt5.types import BrokerStateFrame
    from types import MappingProxyType
    from helpers import make_position_row

    row = make_position_row(ticket=1, magic=BOT, volume=0.2)

    def _make_frame(positions):
        return BrokerStateFrame(
            frame_id=1, cycle_started_m=0, cycle_finished_m=0.01,
            cycle_duration_ms=10, polled_at_wall="2026-07-13T00:00:00Z",
            positions=tuple(positions), account=None,
            ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}),
            errors=(), mt5_last_error=None,
        )

    async def run(pending):
        j = Journal(tmp_path / f"j-{id(pending)}.sqlite")
        bus = EventBus(j)
        await bus.start()
        metrics = GatewayMetrics()
        slot = LatestFrameSlot(metrics)
        c = BrokerStateConsumer(
            bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
            runtime_id="rt", pending=pending,
        )
        await c.process_frame(_make_frame([row]))
        await c.process_frame(_make_frame([]))
        rows = bus.journal.read_events(bus.boot_id, 0, 100)
        types = [event_type(r) for r in rows]
        await bus.close()
        return types

    ext = await run(NullPendingIntentLookup())
    bot = await run(ClosePending({1}))
    assert "trade.closed" in ext
    assert "trade.closed" not in bot
