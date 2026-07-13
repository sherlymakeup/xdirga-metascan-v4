from __future__ import annotations

import asyncio
import threading

import pytest

from helpers import default_account, default_symbol_info
from metascan.mt5.gateway import GatewayConfig, GatewayBootError, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5


def make_gateway(fake: FakeMt5) -> Mt5Gateway:
    fake.set_account(**default_account(login=1))
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm", tick_size=0.01, trade_tick_value_loss=1.0))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    loop = asyncio.get_running_loop()
    return Mt5Gateway(
        fake,
        config=GatewayConfig(login=1, password="p", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=7, poll_interval_ms=20),
        slot=LatestFrameSlot(GatewayMetrics()),
        loop=loop,
        metrics=GatewayMetrics(),
    )


async def test_gateway_serializes_check_and_send_on_gateway_thread() -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 7, "volume": 0.10,
        "price_open": 2300.0, "price_current": 2300.0, "sl": 0.0, "tp": 0.0,
        "profit": 0.0, "swap": 0.0, "type": 0, "time_msc": 0, "identifier": 10, "comment": "",
    }])
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        result = await asyncio.wrap_future(gateway.mutation("cmd-1", "position.close", "10", {}))
        gateway_thread_id = gateway.thread_id
    finally:
        gateway.stop()

    assert result.retcode == 10009
    names = [name for name, _ in fake.call_threads]
    assert names.index("order_check") < names.index("order_send")
    calls = [(name, tid) for name, tid in fake.call_threads if name in {"order_check", "order_send"}]
    assert calls == [("order_check", gateway_thread_id), ("order_send", gateway_thread_id)]


async def test_gateway_maps_market_entry_from_current_tick() -> None:
    fake = FakeMt5()
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        await asyncio.wrap_future(gateway.mutation("entry", "INTERNAL_ENTRY_MARKET", None, {"symbol": "XAUUSDm", "side": "BUY", "volume": 0.1, "stop_loss": 2290.0, "take_profit": 2320.0}))
    finally:
        gateway.stop()

    assert fake.order_send_requests == [{"action": 1, "symbol": "XAUUSDm", "volume": 0.1, "type": 0, "price": 2300.5, "magic": 7, "deviation": 20, "type_filling": 1, "comment": "entry CALIBRATE-SP6", "sl": 2290.0, "tp": 2320.0}]


async def test_gateway_maps_close_partial_protection_and_cancel_hygienically() -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 7, "volume": 0.10,
        "price_open": 2300.0, "price_current": 2300.0, "sl": 2290.0, "tp": 2320.0,
        "profit": 0.0, "swap": 0.0, "type": 0, "time_msc": 0, "identifier": 10, "comment": "",
    }])
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        await asyncio.wrap_future(gateway.mutation("close", "position.close", "10", {"ignored": "value"}))
        await asyncio.wrap_future(gateway.mutation("partial", "position.closePartial", "10", {"volume": 0.03}))
        await asyncio.wrap_future(gateway.mutation("sltp", "position.modifyProtection", "10", {"stop_loss": 2295.0}))
        await asyncio.wrap_future(gateway.mutation("cancel", "order.cancel", "22", {}))
    finally:
        gateway.stop()

    close, partial, protection, cancel = fake.order_send_requests
    assert close == {"action": 1, "position": 10, "symbol": "XAUUSDm", "volume": 0.1, "type": 1, "price": 2300.0, "magic": 7, "deviation": 20, "type_filling": 1, "comment": "close"}
    assert partial["volume"] == 0.03
    assert partial["price"] == 2300.0
    assert protection == {"action": 6, "position": 10, "symbol": "XAUUSDm", "sl": 2295.0, "tp": 2320.0, "magic": 7, "comment": "sltp"}
    assert cancel == {"action": 8, "order": 22, "magic": 7, "comment": "cancel"}


async def test_gateway_rejects_partial_close_with_dust_remainder() -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 7, "volume": 0.019,
        "price_open": 2300.0, "price_current": 2300.0, "sl": 0.0, "tp": 0.0,
        "profit": 0.0, "swap": 0.0, "type": 1, "time_msc": 0, "identifier": 10, "comment": "",
    }])
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        fut = gateway.mutation("partial", "position.closePartial", "10", {"volume": 0.01})
        with pytest.raises(ValueError, match="PARTIAL_CLOSE_DUST_REMAINDER"):
            await asyncio.wrap_future(fut)
    finally:
        gateway.stop()

    assert fake.order_send_requests == []


async def test_gateway_rejects_partial_close_below_min_volume() -> None:
    fake = FakeMt5()
    fake.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 7, "volume": 0.10,
        "price_open": 2300.0, "price_current": 2300.0, "sl": 0.0, "tp": 0.0,
        "profit": 0.0, "swap": 0.0, "type": 1, "time_msc": 0, "identifier": 10, "comment": "",
    }])
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        fut = gateway.mutation("partial", "position.closePartial", "10", {"volume": 0.005})
        with pytest.raises(ValueError, match="PARTIAL_CLOSE_BELOW_MIN_VOLUME"):
            await asyncio.wrap_future(fut)
    finally:
        gateway.stop()

    assert fake.order_send_requests == []


async def test_gateway_rejects_explicit_order_check_failure_without_send() -> None:
    fake = FakeMt5()
    fake.script_order_check(retcode=10006, comment="rejected")
    gateway = make_gateway(fake)
    gateway.start()
    gateway.wait_boot(3.0)
    try:
        result = await asyncio.wrap_future(gateway.mutation("cancel", "order.cancel", "22", {}))
    finally:
        gateway.stop()

    assert result.retcode == 10006
    assert fake.call_log.count("order_send") == 0


def test_fake_mt5_scripts_success_none_exception_slow_and_sent_unknown() -> None:
    fake = FakeMt5()
    fake.script_order_send(retcode=10009, order=11, deal=12)
    fake.script_order_send_none()
    fake.script_order_send_exception(ConnectionError("disconnect"))
    fake.script_order_send_slow(0.001, retcode=10009)
    fake.script_order_send_sent_unknown(order=13, deal=14)

    assert fake.order_send({}).order == 11
    assert fake.order_send({}) is None
    with pytest.raises(ConnectionError, match="disconnect"):
        fake.order_send({})
    assert fake.order_send({}).retcode == 10009
    with pytest.raises(ConnectionError, match="sent unknown"):
        fake.order_send({})
    assert [deal.order for deal in fake.history_deals_get()] == [12, 14]


async def test_gateway_startup_fails_closed_without_loss_tick_metadata() -> None:
    fake = FakeMt5()
    fake.set_account(**default_account(login=1))
    fields = default_symbol_info("XAUUSDm")
    fields.pop("trade_tick_size")
    fields.pop("trade_tick_value_loss")
    fake.add_symbol("XAUUSDm", **fields)
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    gateway = Mt5Gateway(fake, config=GatewayConfig(login=1, password="p", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=7), slot=LatestFrameSlot(GatewayMetrics()), loop=asyncio.get_running_loop(), metrics=GatewayMetrics())
    gateway.start()
    with pytest.raises(GatewayBootError, match="tick metadata"):
        gateway.wait_boot(3.0)
    gateway.stop()
