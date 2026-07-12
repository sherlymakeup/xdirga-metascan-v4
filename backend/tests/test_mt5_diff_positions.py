from __future__ import annotations

from helpers import make_position_row
from metascan.mt5.mapping import (
    closed_trade_payload,
    position_id_for,
    position_payload,
    protection_for,
    sl_or_none,
)


def test_position_id_is_str_ticket() -> None:
    assert position_id_for(42) == "42"


def test_sl_zero_maps_none() -> None:
    assert sl_or_none(0.0) is None
    assert sl_or_none(1.5) == 1.5


def test_protection_levels() -> None:
    assert protection_for(0.0, 0.0) == "UNPROTECTED"
    assert protection_for(1.0, 0.0) == "PARTIALLY_PROTECTED"
    assert protection_for(1.0, 2.0) == "PROTECTED"


def test_closed_trade_exit_reason_manual_and_net_pnl() -> None:
    row = make_position_row(ticket=7, profit=10.0, commission=-1.0, swap=-0.5)
    p = closed_trade_payload(row, closed_at="2026-07-13T00:00:00Z")
    assert p["exitReason"] == "MANUAL"
    assert "MANUAL_CLOSE" not in p.values()
    assert p["netPnl"] == p["grossPnl"] + p["commission"] + p["swap"]
    assert p["positionId"] == "7"
    assert "sp3-no-history" in p["tags"]


def test_position_payload_id() -> None:
    row = make_position_row(ticket=5)
    p = position_payload(row, opened_at="2026-07-13T00:00:00Z")
    assert p["positionId"] == "5"
    assert p["brokerTicket"] == "5"


import asyncio
from pathlib import Path
from helpers import event_type, default_account, default_symbol_info
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


async def _stack(tmp: Path, fake: FakeMt5, pending=None):
    j = Journal(tmp / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_700_000_000_000)
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
    return bus, gw, consumer, sub


async def _collect_until(sub, pred, timeout: float = 5.0):
    end = asyncio.get_event_loop().time() + timeout
    found = []
    while asyncio.get_event_loop().time() < end:
        remaining = end - asyncio.get_event_loop().time()
        try:
            item = await asyncio.wait_for(sub.get(), timeout=max(0.05, remaining))
        except asyncio.TimeoutError:
            break
        found.append(item)
        if pred(found):
            break
    return found


async def test_position_opened_for_bot_magic(tmp_path: Path) -> None:
    fake = FakeMt5()
    bus, gw, consumer, sub = await _stack(tmp_path, fake)
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    events = await _collect_until(
        sub,
        # Check if position.opened event is generated
        lambda xs: any(event_type(e) == "position.opened" for e in xs),
        timeout=5.0,
    )
    types = [event_type(e) for e in events]
    assert "position.opened" in types
    opened = next(e for e in events if event_type(e) == "position.opened")
    assert opened.position_id == "100"
    assert opened.payload["positionId"] == "100"
    assert opened.source == "LOCAL_RUNTIME" or str(opened.source) == "LOCAL_RUNTIME"
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_position_updated_on_mtm(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    bus, gw, consumer, sub = await _stack(tmp_path, fake)
    await _collect_until(
        sub,
        lambda xs: any(event_type(e) == "position.opened" for e in xs),
        timeout=5.0,
    )
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2310.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 50.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    events = await _collect_until(
        sub,
        lambda xs: any(event_type(e) == "position.updated" for e in xs),
        timeout=5.0,
    )
    types = [event_type(e) for e in events]
    assert "position.updated" in types
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_published_events_journaled_monotonic(tmp_path: Path) -> None:
    fake = FakeMt5()
    bus, gw, consumer, sub = await _stack(tmp_path, fake)
    fake.set_positions([{
        "ticket": 100, "symbol": "XAUUSDm", "magic": BOT, "volume": 0.1,
        "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 100, "comment": "",
    }])
    await _collect_until(
        sub,
        lambda xs: any(event_type(e) == "position.opened" for e in xs),
        timeout=5.0,
    )
    stored = bus.journal.read_events(bus.boot_id, 0, 100)
    assert stored
    seqs = [e.sequence for e in stored]
    assert seqs == list(range(1, len(seqs) + 1))
    assert all(e.boot_id == bus.boot_id for e in stored)
    assert all(str(getattr(e.source, "value", e.source)) == "LOCAL_RUNTIME" for e in stored)
    await consumer.stop()
    gw.stop()
    await bus.close()
