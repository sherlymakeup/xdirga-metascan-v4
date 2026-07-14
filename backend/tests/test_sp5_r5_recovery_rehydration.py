"""SP5 Round 5: Restart recovery rehydrates persisted tickets into verification.

Recovered entry intent loads order_ticket/deal_ticket/position_ticket/symbol
into verification payload, emits EXECUTION_UNKNOWN + reconciliation.issue.detected
before scheduling production verifier. Crash stops while mutation unresolved.
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
async def test_crash_while_mutation_unresolved_not_after_failed(tmp_path: Path) -> None:
    """Kill first pipeline while mutation still EXECUTION_UNKNOWN (not FAILED)."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending1 = PendingIntentRegistry()
    facts1 = _make_facts()
    pipeline1 = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=2.0, verify_poll_interval_ms=POLL_MS), pending=pending1, facts=facts1, bot_magic=240101, journal=journal)
    pipeline1.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline1.submit_internal(req, idempotency_key="crash-unresolved")
        await asyncio.sleep(0.6)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN before crash, got {row[0]}"
    finally:
        pipeline1._task.cancel()
        try: await pipeline1._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_recovery_rehydrates_tickets_and_emits_events(tmp_path: Path) -> None:
    """Recovery from journal rehydrates order/deal tickets, emits EXECUTION_UNKNOWN + reconciliation.issue.detected."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending1 = PendingIntentRegistry()
    facts1 = _make_facts()
    pipeline1 = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=2.0, verify_poll_interval_ms=POLL_MS), pending=pending1, facts=facts1, bot_magic=240101, journal=journal)
    pipeline1.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline1.submit_internal(req, idempotency_key="rehydrate-r5")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN"
        intents = journal.recover_entry_intents()
        assert len(intents) == 1
        assert intents[0]["order_ticket"] == 50001
        assert intents[0]["deal_ticket"] == 40001
    finally:
        pipeline1._task.cancel()
        try: await pipeline1._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()

    bus2 = EventBus(journal)
    await bus2.start()
    loop2 = asyncio.get_running_loop()
    fake2 = FakeMt5()
    gw2 = _start_gw(fake2, loop2)
    pending2 = PendingIntentRegistry()
    facts2 = _make_facts()
    sub2 = await bus2.subscribe("r5-recovery-rehydrate", maxsize=256)
    pipeline2 = CommandPipeline(bus=bus2, gateway=gw2, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending2, facts=facts2, bot_magic=240101, journal=journal)
    pipeline2.start()
    try:
        assert pipeline2.mutation_in_flight
        assert pending2.has_pending_entry("XAUUSDm")
        events = []
        for _ in range(20):
            try:
                ev = await asyncio.wait_for(sub2.get(), timeout=0.5)
                events.append(ev)
            except asyncio.TimeoutError:
                break
        types = [event_type(e) for e in events]
        assert "command.execution_unknown" in types, f"expected execution_unknown on recovery, got types={types}"
        assert "reconciliation.issue.detected" in types, f"expected reconciliation.issue.detected on recovery, got types={types}"
    finally:
        await pipeline2.stop()
        gw2.stop()
        await bus2.close()


@pytest.mark.asyncio
async def test_recovery_resolution_correlation_without_old_gateway(tmp_path: Path) -> None:
    """Recovery resolution works using persisted tickets, not old gateway _verification_context."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    pending1 = PendingIntentRegistry()
    facts1 = _make_facts()
    pipeline1 = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=1.0, verify_poll_interval_ms=POLL_MS), pending=pending1, facts=facts1, bot_magic=240101, journal=journal)
    pipeline1.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline1.submit_internal(req, idempotency_key="corr-no-old-gw")
        await asyncio.sleep(0.5)
        assert journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())[0] == "EXECUTION_UNKNOWN"
    finally:
        pipeline1._task.cancel()
        try: await pipeline1._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()

    bus2 = EventBus(journal)
    await bus2.start()
    loop2 = asyncio.get_running_loop()
    fake2 = FakeMt5()
    fake2.set_account(**default_account())
    fake2.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake2.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics2 = GatewayMetrics()
    slot2 = LatestFrameSlot(metrics2)
    cfg2 = GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=240101, poll_interval_ms=50)
    gw2 = Mt5Gateway(fake2, config=cfg2, slot=slot2, loop=loop2, metrics=metrics2)
    gw2.start()
    gw2.wait_boot(timeout=3.0)
    pending2 = PendingIntentRegistry()
    facts2 = _make_facts()
    pipeline2 = CommandPipeline(bus=bus2, gateway=gw2, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending2, facts=facts2, bot_magic=240101, journal=journal)
    async def _position_appears(cmd_id: str):
        await asyncio.sleep(0.3)
        fake2.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": record.command_id[:17]}])
    pipeline2.start()
    try:
        asyncio.create_task(_position_appears(record.command_id))
        await asyncio.sleep(2.0)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=? ORDER BY updated_at DESC", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED from recovery resolve, got {row[0]}"
        assert not pipeline2.mutation_in_flight
        assert not pending2.has_pending_entry("XAUUSDm")
    finally:
        await pipeline2.stop()
        gw2.stop()
        await bus2.close()


@pytest.mark.asyncio
async def test_unresolved_recovery_emits_alert_retains_state(tmp_path: Path) -> None:
    """Recovery that doesn't resolve emits alert/reconciliation-required and retains state."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending1 = PendingIntentRegistry()
    facts1 = _make_facts()
    pipeline1 = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=2.0, verify_poll_interval_ms=POLL_MS), pending=pending1, facts=facts1, bot_magic=240101, journal=journal)
    pipeline1.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline1.submit_internal(req, idempotency_key="unresolved-recovery")
        await asyncio.sleep(0.6)
        assert journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())[0] == "EXECUTION_UNKNOWN"
    finally:
        pipeline1._task.cancel()
        try: await pipeline1._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()

    bus2 = EventBus(journal)
    await bus2.start()
    loop2 = asyncio.get_running_loop()
    fake2 = FakeMt5()
    fake2.set_account(**default_account())
    fake2.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake2.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics2 = GatewayMetrics()
    slot2 = LatestFrameSlot(metrics2)
    cfg2 = GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=240101, poll_interval_ms=50)
    gw2 = Mt5Gateway(fake2, config=cfg2, slot=slot2, loop=loop2, metrics=metrics2)
    gw2.start()
    gw2.wait_boot(timeout=3.0)
    pending2 = PendingIntentRegistry()
    facts2 = _make_facts()
    sub2 = await bus2.subscribe("r5-unresolved", maxsize=256)
    pipeline2 = CommandPipeline(bus=bus2, gateway=gw2, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), verification_timeout_s=0.3, verify_poll_interval_ms=POLL_MS), pending=pending2, facts=facts2, bot_magic=240101, journal=journal)
    pipeline2.start()
    try:
        await asyncio.sleep(0.05)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None and row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN after recovery, got {row[0] if row else None}"
        await asyncio.sleep(2.0)
        assert pipeline2.mutation_in_flight
        assert pending2.has_pending_entry("XAUUSDm")
        events = []
        for _ in range(30):
            try:
                ev = await asyncio.wait_for(sub2.get(), timeout=0.3)
                events.append(ev)
            except asyncio.TimeoutError:
                break
        types = [event_type(e) for e in events]
        assert "alert.created" in types, f"expected alert.created, got types={types}"
    finally:
        await pipeline2.stop()
        gw2.stop()
        await bus2.close()
