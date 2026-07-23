from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayBootError, GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


def _cfg(**over) -> GatewayConfig:
    base = dict(
        login=123456,
        password="secret",
        server="Exness-Trial",
        symbol_suffix="m",
        watchlist_bases=("XAUUSD",),
        bot_magic=240101,
        poll_interval_ms=50,
        require_hedging=True,
    )
    base.update(over)
    return GatewayConfig(**base)


async def test_boot_wrong_login_fails() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=999))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(login=123456), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError):
        gw.wait_boot(timeout=3.0)
    gw.stop()


async def test_boot_missing_symbol_names_base_and_resolved() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456))
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError, match=r"XAUUSD.*XAUUSDm|XAUUSDm.*XAUUSD"):
        gw.wait_boot(timeout=3.0)
    gw.stop()


async def test_boot_hedging_mismatch() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456, margin_mode=0))  # not hedging
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 1.0, 1.1, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(require_hedging=True), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError, match="hedg"):
        gw.wait_boot(timeout=3.0)
    gw.stop()


async def test_boot_trial_environment_rejects_live_account() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456, trade_mode=2))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(broker_environment="TRIAL"), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    with pytest.raises(GatewayBootError, match="environment"):
        gw.wait_boot(timeout=3.0)
    gw.stop()


async def test_verify_preserves_unavailable_read_domains_and_errors() -> None:
    class VerificationMt5:
        def __init__(self) -> None:
            self._positions = [None, ()]
            self._errors = [(101, "positions unavailable"), (202, "orders unavailable"), (303, "deals unavailable")]

        def positions_get(self):
            return self._positions.pop(0)

        def orders_get(self):
            return None

        def history_deals_get(self, *_args):
            return None

        def last_error(self):
            return self._errors.pop(0)

    metrics = GatewayMetrics()
    gateway = Mt5Gateway(
        VerificationMt5(), config=_cfg(), slot=LatestFrameSlot(metrics),
        loop=asyncio.get_running_loop(), metrics=metrics,
    )

    result = gateway._verify_on_gateway_thread("command-1", "position.close", "7", {})

    assert result["positionsAvailable"] is False
    assert result["ordersAvailable"] is False
    assert result["dealsAvailable"] is False
    assert result["positionsError"] == (101, "positions unavailable")
    assert result["ordersError"] == (202, "orders unavailable")
    assert result["dealsError"] == (303, "deals unavailable")
    assert result["positionExists"] is None
    assert result["orderExists"] is None


async def test_boot_success() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=123456))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    loop = asyncio.get_running_loop()
    gw = Mt5Gateway(fake, config=_cfg(), slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)
    assert gw.boot_error is None
    frame = await asyncio.wait_for(slot.take(), timeout=2.0)
    assert frame.frame_id >= 1
    assert "XAUUSDm" in frame.symbol_meta
    gw.stop()
