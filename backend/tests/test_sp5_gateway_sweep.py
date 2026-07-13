from __future__ import annotations

import asyncio

import pytest

from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5
from helpers import default_account, default_symbol_info


@pytest.mark.asyncio
async def test_gateway_sweep_facts_read_orders_on_gateway_thread() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account())
    fake.add_symbol("EURUSDm", **default_symbol_info("EURUSDm"))
    fake.set_tick("EURUSDm", 1.0, 1.1, 1)
    fake.set_orders([{"ticket": 7, "symbol": "EURUSDm", "magic": 240101, "volume_current": 0.1, "type": 2}])
    loop = asyncio.get_running_loop()
    gateway = Mt5Gateway(fake, config=GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("EURUSD",), bot_magic=240101), slot=LatestFrameSlot(GatewayMetrics()), loop=loop, metrics=GatewayMetrics())
    gateway.start()
    gateway.wait_boot()
    try:
        facts = await asyncio.wrap_future(gateway.sweep_facts())
        assert facts["orders"][0]["ticket"] == 7
        assert facts["positions"] == ()
        assert {thread for name, thread in fake.call_threads if name == "orders_get"} == {gateway.thread_id}
    finally:
        gateway.stop()
