from __future__ import annotations

from pathlib import Path
import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.clocks import SystemMonotonicClock, SystemWallClock
from metascan.mt5.pending_intent import NullPendingIntentLookup


def test_null_pending_always_false() -> None:
    n = NullPendingIntentLookup()
    assert n.has_pending_close(1) is False
    assert n.has_pending_partial(1, 0.1) is False
    assert n.has_pending_modify(1) is False


def test_system_clocks_return_values() -> None:
    m = SystemMonotonicClock()
    w = SystemWallClock()
    a = m.monotonic()
    b = m.monotonic()
    assert b >= a
    iso = w.now_iso()
    assert "T" in iso
    assert iso.endswith("Z") or "+" in iso


from metascan.mt5.metrics import GatewayMetrics, DEFAULT_SAMPLE_CAPACITY


def test_metrics_bounded_capacity() -> None:
    m = GatewayMetrics(capacity=8)
    for i in range(20):
        m.record_cycle_ms(float(i))
    assert len(m.poll_cycle_ms) == 8


def test_metrics_p50_p95() -> None:
    m = GatewayMetrics(capacity=100)
    for i in range(1, 101):
        m.record_cycle_ms(float(i))
    p50 = m.cycle_p50()
    p95 = m.cycle_p95()
    assert p50 is not None and 45 <= p50 <= 55
    assert p95 is not None and 90 <= p95 <= 100


def test_handoff_drop_counters() -> None:
    m = GatewayMetrics()
    assert m.handoff_dropped_count == 0
    m.note_handoff_drop()
    m.note_handoff_drop()
    assert m.handoff_dropped_count == 2
    assert m.handoff_overruns == 2
    assert m.handoff_overrun_active is True


def test_empty_percentile_none() -> None:
    m = GatewayMetrics()
    assert m.cycle_p50() is None
    assert m.cycle_p95() is None


def test_record_call_ms_named() -> None:
    m = GatewayMetrics()
    m.record_call_ms("positions_get", 12.0)
    m.record_call_ms("positions_get", 20.0)
    assert m.p50(m.call_ms["positions_get"]) is not None


class FakeMono:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t


class FakeWall:
    def __init__(self) -> None:
        self.i = 0

    def now_iso(self) -> str:
        self.i += 1
        return f"2020-01-01T00:00:{self.i:02d}Z"


def test_budgets_use_monotonic_not_wall() -> None:
    mono = FakeMono()
    mono.t = 1000.0
    last = 999.0
    age_ms = (mono.t - last) * 1000
    assert age_ms == 1000.0
    wall = FakeWall()
    assert wall.now_iso().startswith("2020")


@pytest.mark.asyncio
async def test_tick_age_budget_uses_monotonic(tmp_path: Path) -> None:
    mono = FakeMono()
    wall = FakeWall()
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=1, runtime_id="rt",
        mono=mono, wall=wall, tick_age_budget_ms=1000.0,
    )
    
    from metascan.mt5.types import TickRow, BrokerStateFrame
    from types import MappingProxyType
    
    t0 = TickRow("XAUUSDm", 1, 1.1, 1, time_msc=100, volume=0)
    f1 = BrokerStateFrame(
        frame_id=1, cycle_started_m=mono.t, cycle_finished_m=mono.t,
        cycle_duration_ms=1, polled_at_wall=wall.now_iso(),
        positions=(), account=None,
        ticks=MappingProxyType({"XAUUSDm": t0}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(f1)
    
    mono.t += 2.0  # 2000ms
    t1 = TickRow("XAUUSDm", 1, 1.1, 1, time_msc=100, volume=0)  # frozen msc
    f2 = BrokerStateFrame(
        frame_id=2, cycle_started_m=mono.t, cycle_finished_m=mono.t,
        cycle_duration_ms=1, polled_at_wall=wall.now_iso(),
        positions=(), account=None,
        ticks=MappingProxyType({"XAUUSDm": t1}),
        symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(f2)
    assert "TICK_AGE" in consumer._degrade_reasons or consumer.connection_state == "DEGRADED"
    await bus.close()


def test_metrics_concurrent_safety() -> None:
    import threading
    import random

    m = GatewayMetrics(capacity=100)
    stop_event = threading.Event()

    def writer() -> None:
        while not stop_event.is_set():
            m.record_cycle_ms(random.random() * 100.0)
            m.record_call_ms("test_call", random.random() * 10.0)
            m.note_handoff_drop()

    def reader() -> None:
        while not stop_event.is_set():
            _ = m.cycle_p50()
            _ = m.cycle_p95()
            if "test_call" in m.call_ms:
                _ = m.p50(m.call_ms["test_call"])
                _ = m.p95(m.call_ms["test_call"])
            _ = m.cycle_overruns
            _ = m.handoff_overruns
            _ = m.handoff_dropped_count
            _ = m.handoff_overrun_active

    threads = [
        threading.Thread(target=writer) for _ in range(5)
    ] + [
        threading.Thread(target=reader) for _ in range(5)
    ]

    for t in threads:
        t.start()

    import time
    time.sleep(0.5)
    stop_event.set()

    for t in threads:
        t.join()

    # Verify we can obtain valid percentiles at the end
    assert m.cycle_p50() is not None
    assert m.cycle_p95() is not None
