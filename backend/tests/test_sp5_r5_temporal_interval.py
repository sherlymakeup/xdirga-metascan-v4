"""SP5 Round 5 review: temporal verifier interval honor and exact deadline."""
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


def _make_facts(**kw) -> RuntimeFactsProvider:
    base = dict(
        runtime_state="READY", entries_enabled=True, safety_mode_active=False,
        trading_halt=False, account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"XAUUSDm": {"bid": 2300.0, "ask": 2300.5, "age_ms": 0}},
        symbol_meta={"XAUUSDm": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "age_ms": 0}},
    )
    base.update(kw)
    return RuntimeFactsProvider.current(**base)


@pytest.mark.asyncio
async def test_negative_only_after_full_budget_exactly_at_deadline(tmp_path: Path) -> None:
    """Entry without position: False verdict only after full budget, not extra cycle."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=0.6, verify_poll_interval_ms=100), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="deadline-exact")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN at 0.3s (before deadline), got {row[0]}"
        await asyncio.sleep(0.8)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN after full budget deadline, got {row[0]}"
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_honors_configured_interval_between_polls(tmp_path: Path) -> None:
    """Temporal verifier sleeps for full configured interval between verify calls."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send(retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=5, verification_timeout_s=0.8, verify_poll_interval_ms=300), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="interval-honor")
        await asyncio.sleep(0.15)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row[0] == "EXECUTION_UNKNOWN"
        call_count_early = len(fake.call_log)
        await asyncio.sleep(0.35)
        call_count_mid = len(fake.call_log)
        extra_calls_early = call_count_mid - call_count_early
        await asyncio.sleep(1.0)
        call_count_total = len(fake.call_log) - call_count_early
        assert extra_calls_early <= 30, f"too many calls in first 0.35s (interval 300ms): {extra_calls_early}"
        assert call_count_total <= 90, f"too many total calls in 1.35s (interval 300ms): {call_count_total}"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()
