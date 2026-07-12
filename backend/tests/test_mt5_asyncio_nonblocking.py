from __future__ import annotations

import asyncio
import time

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


async def test_blocking_positions_get_does_not_freeze_loop() -> None:
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
            watchlist_bases=("XAUUSD",), bot_magic=1, poll_interval_ms=50,
        ),
        slot=slot, loop=loop, metrics=metrics,
    )
    gw.start()
    gw.wait_boot(3.0)
    fake.block_call("positions_get", 0.3)
    ticks = 0

    async def counter() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    t0 = time.monotonic()
    await counter()
    elapsed = time.monotonic() - t0
    gw.stop()
    assert ticks == 10
    assert elapsed < 0.35
