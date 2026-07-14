"""SP5 Round 6: Temporal verifier race condition — max one in-flight, no drift, boundary win."""
from __future__ import annotations

import asyncio
import concurrent.futures
import time as time_mod
from pathlib import Path

import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.mt5.gateway import Mt5Gateway, GatewayConfig
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from helpers import default_account, default_symbol_info


POLL_MS = 50


class VerifyCallTiming:
    def __init__(self, gw: Mt5Gateway) -> None:
        self._verify_original = gw.verify
        self.calls: list[tuple[float, float]] = []
        self._in_flight = 0
        self.max_in_flight = 0

    def verify(self, command_id: str, kind: str, target_id: str | None, request: dict) -> concurrent.futures.Future:
        start = time_mod.monotonic()
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        inner: concurrent.futures.Future = self._verify_original(command_id, kind, target_id, request)
        outer: concurrent.futures.Future = concurrent.futures.Future()

        def _on_done(f: concurrent.futures.Future) -> None:
            end = time_mod.monotonic()
            self.calls.append((start, end))
            self._in_flight -= 1
            try:
                outer.set_result(f.result())
            except BaseException as exc:
                outer.set_exception(exc)

        inner.add_done_callback(_on_done)
        return outer


def _start_gw(fake: FakeMt5, loop: asyncio.AbstractEventLoop) -> Mt5Gateway:
    fake.set_account(**default_account())
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    cfg = GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=240101, poll_interval_ms=50)
    gw = Mt5Gateway(fake, config=cfg, slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)
    return gw


def _make_facts(**kw: object) -> RuntimeFactsProvider:
    base: dict[str, object] = dict(
        runtime_state="READY", entries_enabled=True, safety_mode_active=False,
        trading_halt=False, account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"XAUUSDm": {"bid": 2300.0, "ask": 2300.5, "age_ms": 0}},
        symbol_meta={"XAUUSDm": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "age_ms": 0}},
    )
    base.update(**kw)
    return RuntimeFactsProvider.current(**base)


# ── Test A: equal cadence — 50ms gateway delay, 50ms interval, convergence before deadline ──

@pytest.mark.asyncio
async def test_a_equal_cadence_50ms_delay_converges(tmp_path: Path) -> None:
    """Verify convergence when gateway delay matches poll interval."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    fake._block_seconds_recurring = {"positions_get": 0.025}
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=1.0, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="a-equal-cadence")
        await asyncio.sleep(0.15)
        fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": record.command_id[:17]}])
        fake.freeze_ticks()
        await asyncio.sleep(2.0)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None, "command row not found"
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight, "expected lock released"
    finally:
        pipeline._task.cancel()
        try:
            await pipeline._task
        except asyncio.CancelledError:
            pass
        gw.stop()
        await bus.close()


# ── Test B: call duration > interval < budget consumed ──

@pytest.mark.asyncio
async def test_b_duration_exceeds_interval_still_converges(tmp_path: Path) -> None:
    """Verify convergence when each verify call takes longer than poll interval."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    fake._block_seconds_recurring = {"positions_get": 0.05}
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=1.0, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="b-dur-exceeds-int")
        await asyncio.sleep(0.15)
        fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": record.command_id[:17]}])
        fake.freeze_ticks()
        await asyncio.sleep(2.0)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None, "command row not found"
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight, "expected lock released"
    finally:
        pipeline._task.cancel()
        try:
            await pipeline._task
        except asyncio.CancelledError:
            pass
        gw.stop()
        await bus.close()


# ── Test C: max in-flight = 1, no buildup ──

@pytest.mark.asyncio
async def test_c_max_one_in_flight_no_buildup(tmp_path: Path) -> None:
    """Instrument verify call start/end — assert max in-flight = 1, no call overlap."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    fake._block_seconds_recurring = {"positions_get": 0.05}
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.8, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    timing = VerifyCallTiming(gw)
    gw.verify = timing.verify
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="c-max-inflight")
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None, "command row not found"
        assert timing.max_in_flight <= 1, f"max concurrent verify calls = {timing.max_in_flight}, expected <= 1"
        assert len(timing.calls) > 0, "expected at least one verify call"
        for i in range(len(timing.calls) - 1):
            _, prev_end = timing.calls[i]
            next_start, _ = timing.calls[i + 1]
            assert prev_end <= next_start + 0.05, f"call overlap: call {i} ends at {prev_end}, call {i+1} starts at {next_start}"
    finally:
        pipeline._task.cancel()
        try:
            await pipeline._task
        except asyncio.CancelledError:
            pass
        gw.stop()
        await bus.close()


# ── Test D: call-start spacing honors interval with narrow tolerance ──

@pytest.mark.asyncio
async def test_d_call_start_spacing_honors_interval(tmp_path: Path) -> None:
    """Assert consecutive verify call starts spaced by >= interval with tolerance."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    fake._block_seconds_recurring = {"positions_get": 0.015}
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.8, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    timing = VerifyCallTiming(gw)
    gw.verify = timing.verify
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="d-spacing")
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None, "command row not found"
        starts = [s for s, _ in timing.calls]
        assert len(starts) >= 2, f"expected >= 2 verify calls, got {len(starts)}"
        interval_s = POLL_MS / 1000.0
        tolerance = 0.02
        for i in range(len(starts) - 1):
            gap = starts[i + 1] - starts[i]
            assert gap >= interval_s - tolerance, f"call spacing {i}->{i+1}: {gap:.4f}s < {interval_s - tolerance:.4f}s (tolerance {tolerance:.4f}s)"
    finally:
        pipeline._task.cancel()
        try:
            await pipeline._task
        except asyncio.CancelledError:
            pass
        gw.stop()
        await bus.close()


# ── Test E: near-deadline completion consumed ──

@pytest.mark.asyncio
async def test_e_near_deadline_completion_consumed(tmp_path: Path) -> None:
    """Result from verify future that completes at deadline boundary is consumed."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.5, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="e-boundary")

        async def _delayed_position_boundary():
            await asyncio.sleep(0.48)
            fake.set_positions([{"ticket": 4001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 4001, "comment": record.command_id[:17]}])
            fake.freeze_ticks()

        asyncio.create_task(_delayed_position_boundary())
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None, "command row not found"
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight, "expected lock released"
    finally:
        pipeline._task.cancel()
        try:
            await pipeline._task
        except asyncio.CancelledError:
            pass
        gw.stop()
        await bus.close()
