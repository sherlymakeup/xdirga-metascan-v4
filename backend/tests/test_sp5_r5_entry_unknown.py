"""SP5 Round 5: Entry lacking confirmed position → EXECUTION_UNKNOWN with full-budget verification.

Successful INTERNAL_ENTRY_MARKET mutation but no position → persist order/deal,
transition EXECUTION_UNKNOWN, retain journal/registry/lock, full-budget verify.
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
from helpers import default_account, default_symbol_info, event_type


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
async def test_entry_lacking_position_goes_execution_unknown(tmp_path: Path) -> None:
    """Mutation returns success but no position → EXECUTION_UNKNOWN with order/deal persisted."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    sub = await bus.subscribe("r5-entry-unknown", maxsize=256)
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=0.3, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="entry-no-pos")
        await asyncio.sleep(0.8)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
        events = []
        for _ in range(30):
            try:
                ev = await asyncio.wait_for(sub.get(), timeout=0.3)
                events.append(ev)
                if event_type(ev) in ("command.failed", "command.completed", "alert.created"):
                    pass
            except asyncio.TimeoutError:
                break
        types = [event_type(e) for e in events]
        assert "command.execution_unknown" in types, f"expected execution_unknown, got types={types}"
        assert "reconciliation.issue.detected" in types, f"expected reconciliation.issue.detected, got types={types}"
        intents = journal.recover_entry_intents()
        assert len(intents) == 1
        assert intents[0]["order_ticket"] == 50001
        assert intents[0]["deal_ticket"] == 40001
        assert pending.has_pending_entry("XAUUSDm")
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_duplicate_entry_rejected_during_gap(tmp_path: Path) -> None:
    """Second entry rejected MUTATION_SCOPE_LOCKED while first in EXECUTION_UNKNOWN gap."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=2.0, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        r1 = await pipeline.submit_internal(req, idempotency_key="dup-gap-1")
        for _ in range(50):
            await asyncio.sleep(0.05)
            r1_row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r1.command_id,)).fetchone())
            if r1_row and r1_row[0] == "EXECUTION_UNKNOWN":
                break
        r1_row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r1.command_id,)).fetchone())
        assert r1_row is not None
        assert r1_row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN before duplicate, got {r1_row[0]}"
        r2 = await pipeline.submit_internal(req, idempotency_key="dup-gap-2")
        for _ in range(100):
            await asyncio.sleep(0.05)
            r2_row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r2.command_id,)).fetchone())
            if r2_row and r2_row[0] in ("FAILED", "COMPLETED", "EXECUTION_UNKNOWN"):
                break
        r2_row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (r2.command_id,)).fetchone())
        assert r2_row is not None
        assert r2_row[0] == "FAILED", f"expected FAILED, got {r2_row[0]}"
        assert pending.has_pending_entry("XAUUSDm")
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_position_appears_during_verify_then_completed(tmp_path: Path) -> None:
    """Position appears during temporal verification → COMPLETED with ticket upgrade."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="pos-appears-r5")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN"
        fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": record.command_id[:17]}])
        fake.freeze_ticks()
        await asyncio.sleep(2.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
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
async def test_ambiguity_retains_durable_state_and_alert(tmp_path: Path) -> None:
    """Ambiguity retains journal entry intent, registry entry, lock, and emits alert."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    sub = await bus.subscribe("r5-ambig-alert", maxsize=256)
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=0.3, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101, journal=journal)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="ambig-alert-r5")
        await asyncio.sleep(1.0)
        intents = journal.recover_entry_intents()
        assert len(intents) == 1
        assert intents[0]["state"] == "PENDING"
        assert pending.has_pending_entry("XAUUSDm")
        assert pipeline.mutation_in_flight
        events = []
        for _ in range(30):
            try:
                ev = await asyncio.wait_for(sub.get(), timeout=0.3)
                events.append(ev)
            except asyncio.TimeoutError:
                break
        types = [event_type(e) for e in events]
        assert "alert.created" in types
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()
