from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


async def test_all_mt5_calls_same_thread() -> None:
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
            watchlist_bases=("XAUUSD",), bot_magic=1, poll_interval_ms=40,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    gw.start()
    gw.wait_boot(3.0)
    await asyncio.wait_for(slot.take(), timeout=2.0)
    await asyncio.wait_for(slot.take(), timeout=2.0)
    gw.stop()
    assert fake.call_threads
    ids = {tid for _, tid in fake.call_threads}
    assert len(ids) == 1
    names = {n for n, _ in fake.call_threads}
    assert "initialize" in names
    assert "positions_get" in names
    assert "account_info" in names
