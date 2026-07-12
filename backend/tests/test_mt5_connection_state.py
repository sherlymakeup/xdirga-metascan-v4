from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType

import pytest

from helpers import default_account, default_symbol_info, event_type
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import BrokerStateFrame
from metascan.mt5.testing.fake_mt5 import FakeMt5

BOT = 240101


async def test_connected_after_successful_poll(tmp_path: Path) -> None:
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
    
    await asyncio.sleep(0.15)
    assert consumer.connection_state == "CONNECTED"
    
    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_handoff_overrun_marks_degraded(tmp_path: Path) -> None:
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1",
    )
    
    metrics.note_handoff_drop()
    frame = BrokerStateFrame(
        frame_id=1, cycle_started_m=0, cycle_finished_m=0.01,
        cycle_duration_ms=10, polled_at_wall="2026-07-13T00:00:00Z",
        positions=(), account=None, ticks=MappingProxyType({}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=(0, "OK"),
    )
    published = await consumer.process_frame(frame)
    assert consumer.connection_state == "DEGRADED"
    types = [event_type(e) for e in published]
    assert "broker.connection.changed" in types
    conn = next(e for e in published if event_type(e) == "broker.connection.changed")
    assert conn.payload["state"] == "DEGRADED"
    assert "HANDOFF_OVERRUN" in conn.payload["reasons"]
    
    await bus.close()


async def test_coalesce_drop_count_integration(tmp_path: Path) -> None:
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
    # Don't start consumer so slot remains unconsumed
    gw.start()
    gw.wait_boot(3.0)
    await asyncio.sleep(0.3)
    assert metrics.handoff_dropped_count >= 1
    frame = await asyncio.wait_for(slot.take(), timeout=2)
    assert frame.frame_id >= 2
    gw.stop()
    await bus.close()


async def test_poll_failures_and_recovery_transitions(tmp_path: Path) -> None:
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
    # Use hard_fail_threshold = 3 for quicker test
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", hard_fail_threshold=3,
    )
    gw.start()
    gw.wait_boot(3.0)
    consumer.start()

    sub = await bus.subscribe("sub1", maxsize=100)

    # Helper to wait for a state event
    async def wait_for_state(target_state: str, timeout: float = 3.0) -> None:
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            try:
                e = await asyncio.wait_for(sub.get(), timeout=0.1)
                if event_type(e) == "broker.connection.changed" and e.payload.get("state") == target_state:
                    return
            except asyncio.TimeoutError:
                continue
        raise TimeoutError(f"Timed out waiting for connection state: {target_state}")

    # 1. Connected state initially
    await wait_for_state("CONNECTED")

    # 2. Trigger single cycle error -> DEGRADED
    fake.fail_next("positions_get", times=1)
    await wait_for_state("DEGRADED")
    assert "SOFT_ERROR" in consumer._degrade_reasons

    # 3. Recover back to CONNECTED
    await wait_for_state("CONNECTED")

    # 4. Trigger sustained error (consecutive errors >= threshold) -> DISCONNECTED
    fake.fail_next("positions_get", times=4)
    await wait_for_state("DISCONNECTED")

    # 5. Recover again to CONNECTED
    await wait_for_state("CONNECTED")

    await consumer.stop()
    gw.stop()
    await bus.close()


async def test_heartbeat_timeout_transitions_disconnected(tmp_path: Path) -> None:
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    # Inactive/frozen gateway (no frames produced).
    # Consumer should transition to DISCONNECTED after heartbeat timeout.
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", heartbeat_timeout_ms=100.0,
    )
    consumer.start()

    await asyncio.sleep(0.25)
    assert consumer.connection_state == "DISCONNECTED"
    assert "HARD_FAIL" in consumer._degrade_reasons

    await consumer.stop()
    await bus.close()
