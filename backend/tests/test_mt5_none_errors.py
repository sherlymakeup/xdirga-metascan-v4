from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


async def test_positions_get_none_with_error_no_crash(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    
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

    # Now make positions_get return None with error code
    fake.set_return("positions_get", None)
    fake.set_last_error(1, "IPC failed")
    
    await asyncio.sleep(0.3)
    
    # gateway still alive
    assert gw._thread is not None and gw._thread.is_alive()
    # consumer not crashed
    assert consumer._task is not None and not consumer._task.done()

    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_account_info_none_frame_account_none(tmp_path: Path) -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    
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
    gw.start()
    gw.wait_boot(3.0)
    
    # consume first frame
    await asyncio.wait_for(slot.take(), timeout=2.0)
    
    fake.set_return("account_info", None)
    fake.set_last_error(1, "Acc fail")
    
    frame = await asyncio.wait_for(slot.take(), timeout=2.0)
    assert frame.account is None
    assert any(e.call == "account_info" for e in frame.errors)
    
    gw.stop()
