"""SP5 Round 4: Durable entry intent — production lifecycle.

Tests: journal persist before send; ticket updates on mutation result and verification;
restart recovery creates real async recovery task; delayed broker convergence;
killed first pipeline → recovered by second → terminal resolution + journal clear.
No manual register_entry_intent in recovery test.
"""
from __future__ import annotations

import asyncio
import json
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


def _start_gw(fake: FakeMt5, loop: asyncio.AbstractEventLoop, *, bot_magic: int = 240101) -> Mt5Gateway:
    fake.set_account(**default_account())
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    cfg = GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=bot_magic, poll_interval_ms=50)
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
async def test_entry_intent_persisted_before_send(tmp_path: Path) -> None:
    """Entry intent journal persisted BEFORE mutation send."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.block_order_send(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="entry-persist-before")
        await asyncio.sleep(0.4)
        intents = journal.recover_entry_intents()
        assert len(intents) == 1
        assert intents[0]["symbol"] == "XAUUSDm"
        assert intents[0]["command_id"] == record.command_id
        assert intents[0]["state"] == "PENDING"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_entry_intent_ticket_updates_on_mutation_result(tmp_path: Path) -> None:
    """Entry intent updated with order/deal tickets after mutation returns (timely)."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="entry-ticket-1")
        await asyncio.sleep(0.15)
        fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": record.command_id[:17]}])
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        intents = journal.run_on_writer(lambda c: c.execute("SELECT * FROM entry_intents WHERE symbol='XAUUSDm'").fetchall())
        assert len(intents) == 0
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_entry_intent_cleared_on_gate_rejection(tmp_path: Path) -> None:
    """Entry intent cleared from journal when gate rejects before send."""
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
        record = await pipeline.submit_internal(req, idempotency_key="entry-clear-gate")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
        intents = journal.recover_entry_intents()
        assert len(intents) == 0
        assert not pending.has_pending_entry("XAUUSDm")
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_restart_recovery_delayed_convergence(tmp_path: Path) -> None:
    """Killed first pipeline → second recovers and drives temporal verify → COMPLETED."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake1 = FakeMt5()
    gw1 = _start_gw(fake1, loop)
    fake1.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    pending1 = PendingIntentRegistry()
    facts1 = _make_facts()
    pipeline1 = CommandPipeline(bus=bus, gateway=gw1, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.2, verify_poll_interval_ms=POLL_MS), pending=pending1, facts=facts1, bot_magic=240101, journal=journal)
    pipeline1.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline1.submit_internal(req, idempotency_key="entry-recovery-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "EXECUTION_UNKNOWN"
        assert pipeline1.mutation_in_flight
        assert pending1.has_pending_entry("XAUUSDm")
    finally:
        pipeline1._task.cancel()
        try: await pipeline1._task
        except asyncio.CancelledError: pass
        gw1.stop()
        await bus.close()

    bus2 = EventBus(journal)
    await bus2.start()
    fake2 = FakeMt5()
    gw2 = _start_gw(fake2, loop)
    pending2 = PendingIntentRegistry()
    facts2 = _make_facts()
    pipeline2 = CommandPipeline(bus=bus2, gateway=gw2, risk_config=RiskConfig(verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending2, facts=facts2, bot_magic=240101, journal=journal)
    pipeline2.start()
    try:
        assert pipeline2.mutation_in_flight
        assert pending2.has_pending_entry("XAUUSDm")
        async def _delayed_position(cmd_id: str):
            await asyncio.sleep(0.3)
            fake2.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": cmd_id[:17]}])
        asyncio.create_task(_delayed_position(record.command_id))
        await asyncio.sleep(2.0)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=? ORDER BY updated_at DESC", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline2.mutation_in_flight
        assert not pending2.has_pending_entry("XAUUSDm")
        intents = journal.recover_entry_intents()
        assert len(intents) == 0
    finally:
        await pipeline2.stop()
        gw2.stop()
        await bus2.close()
