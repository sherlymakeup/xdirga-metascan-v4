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
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


class PartialPending:
    def __init__(self, key: tuple[int, float] | None = None) -> None:
        self.key = key

    def has_pending_close(self, ticket: int) -> bool:
        return False

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return self.key is not None and self.key == (ticket, volume)

    def has_pending_modify(self, ticket: int) -> bool:
        return False

    def get_command_id(self, ticket: int) -> str | None:
        return "cmd-partial-77" if self.key and self.key[0] == ticket else None

    def get_correlation_id(self, ticket: int) -> str | None:
        return "corr-partial-77" if self.key and self.key[0] == ticket else None

    def clear(self, ticket: int) -> None:
        if self.key and self.key[0] == ticket:
            self.key = None


async def _boot(tmp_path, pending=None):
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    fake.set_positions([{
        "ticket": 77, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.30,
        "price_open": 2300.0, "price_current": 2305.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 10.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 77, "comment": "",
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
        runtime_id="rt1", pending=pending,
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


async def test_external_partial(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot(tmp_path)
    fake.set_volume(77, 0.10)
    seen = []
    end = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2)
        if hasattr(e, "type"):
            seen.append(event_type(e))
            if "position.partially_closed" in seen:
                break
    assert "position.partially_closed" in seen
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    partial = next(r for r in rows if event_type(r) == "position.partially_closed")
    assert partial.payload["positionId"] == "77"
    assert partial.payload["previousVolume"] == 0.30
    assert partial.payload["newVolume"] == 0.10
    assert abs(partial.payload["closedVolume"] - 0.20) < 1e-9
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_pending_partial_emits_correlated_events(tmp_path: Path) -> None:
    bus, gw, consumer, sub, fake = await _boot(tmp_path, pending=PartialPending((77, 0.10)))
    fake.set_volume(77, 0.10)
    seen = []
    end = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < end:
        try:
            e = await asyncio.wait_for(sub.get(), timeout=0.2)
        except asyncio.TimeoutError:
            break
        if hasattr(e, "type"):
            seen.append(event_type(e))
    assert "position.partially_closed" in seen
    assert "position.updated" in seen
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    partial = next(r for r in rows if event_type(r) == "position.partially_closed")
    updated = next(r for r in rows if event_type(r) == "position.updated")
    assert partial.command_id == updated.command_id == "cmd-partial-77"
    assert partial.correlation_id == updated.correlation_id == "corr-partial-77"
    assert consumer.last_positions[77].volume == 0.10
    await consumer.stop()
    gw.stop()
    await bus.close()
