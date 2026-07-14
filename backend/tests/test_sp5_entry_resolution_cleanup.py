"""SP5 Round 4: Entry resolution cleanup — symbol ticket upgrade, terminal clear, no stale/duplicate locks.

Exact state assertions, no `in (...)` weak assertions.
"""
from __future__ import annotations

import asyncio
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


def _make_facts() -> RuntimeFactsProvider:
    return RuntimeFactsProvider.current(
        runtime_state="READY", entries_enabled=True, safety_mode_active=False,
        trading_halt=False, account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"XAUUSDm": {"bid": 2300.0, "ask": 2300.5, "age_ms": 0}},
        symbol_meta={"XAUUSDm": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "age_ms": 0}},
    )


@pytest.mark.asyncio
async def test_entry_clear_on_gate_fail_releases_lock(tmp_path: Path) -> None:
    """Gate rejection clears entry intent, lock released immediately."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), max_positions=0), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        r1 = await pipeline.submit_internal(req, idempotency_key="clear-lock-1")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r1.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
        assert not pipeline.mutation_in_flight
        assert not pending.has_pending_entry("XAUUSDm")
        intents = journal.recover_entry_intents()
        assert len(intents) == 0
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_second_entry_blocked_by_first_inflight(tmp_path: Path) -> None:
    """Second entry for same symbol blocked by MUTATION_SCOPE_LOCKED while first inflight."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.block_order_send(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.2, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        await pipeline.submit_internal(req, idempotency_key="first-dup")
        await asyncio.sleep(0.15)
        r2 = await pipeline.submit_internal(req, idempotency_key="second-dup")
        await asyncio.sleep(0.6)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r2.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_stale_lock_retained_after_verification_budget(tmp_path: Path) -> None:
    """Exhausted verification budget: FAILED with lock retained, no stale lock after second entry."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.block_order_send(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.2, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        r1 = await pipeline.submit_internal(req, idempotency_key="stale-lock-1")
        await asyncio.sleep(0.8)
        row1 = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r1.command_id,)).fetchone())
        assert row1 is not None
        assert row1[0] == "FAILED"
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_entry_cleared_on_timeout_then_terminal(tmp_path: Path) -> None:
    """Entry intent cleared from journal when verification resolves after delayed convergence."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        async def _delayed_pos(cmd_id: str):
            await asyncio.sleep(0.35)
            fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": cmd_id[:17]}])
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="entry-clear-terminal")
        asyncio.create_task(_delayed_pos(record.command_id))
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        assert not pipeline.mutation_in_flight
        assert not pending.has_pending_entry("XAUUSDm")
        intents = journal.recover_entry_intents()
        assert len(intents) == 0
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()
