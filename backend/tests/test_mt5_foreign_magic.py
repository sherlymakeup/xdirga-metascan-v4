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


async def test_foreign_magic_degraded_and_critical_alert(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    
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
        runtime_id="rt1",
    )
    gw.start()
    gw.wait_boot(3.0)
    consumer.start()
    sub = await bus.subscribe("s1", maxsize=2048)

    # Now add a foreign position
    fake.set_positions([{
        "ticket": 999, "symbol": "XAUUSDm", "magic": 111,
        "volume": 0.1, "price_open": 2300.0, "price_current": 2301.0,
        "sl": 0.0, "tp": 0.0, "profit": 0.0, "swap": 0.0, "commission": 0.0,
        "type": 0, "time_msc": 0, "identifier": 999, "comment": "manual",
    }])

    # Wait for alert.created or connection DEGRADED
    seen = []
    end = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < end:
        e = await asyncio.wait_for(sub.get(), timeout=2.0)
        if hasattr(e, "type"):
            seen.append(event_type(e))
            if "alert.created" in seen and consumer.connection_state == "DEGRADED":
                break

    assert "alert.created" in seen
    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    alert = next(r for r in rows if event_type(r) == "alert.created")
    assert alert.payload["severity"] == "CRITICAL"
    assert "999" in alert.payload["description"]
    assert "111" in alert.payload["description"]
    assert 999 not in consumer.last_positions
    assert consumer.connection_state == "DEGRADED"
    assert 999 in consumer.quarantine_tickets

    # Clean the positions
    fake.set_positions([])
    # Wait for state to go back to CONNECTED
    end = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < end:
        await asyncio.sleep(0.05)
        if consumer.connection_state == "CONNECTED":
            break
    assert consumer.connection_state == "CONNECTED"
    assert not consumer.quarantine_tickets

    await consumer.stop()
    gw.stop()
    await bus.close()
