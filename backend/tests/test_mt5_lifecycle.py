from __future__ import annotations

from pathlib import Path

import pytest


def test_gateway_source_has_no_order_send() -> None:
    root = Path("src/metascan/mt5")
    for path in root.rglob("*.py"):
        if "testing" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "order_send" not in text, path
        assert "order_check" not in text, path
        assert "history_deals_get" not in text, path


async def test_stop_calls_shutdown() -> None:
    import asyncio
    from helpers import default_account, default_symbol_info
    from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
    from metascan.mt5.handoff import LatestFrameSlot
    from metascan.mt5.metrics import GatewayMetrics
    from metascan.mt5.testing.fake_mt5 import FakeMt5

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
    gw.stop(join_timeout=3.0)
    assert "shutdown" in fake.call_log
