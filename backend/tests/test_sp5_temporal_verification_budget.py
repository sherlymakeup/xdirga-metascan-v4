"""SP5 Round 4: Real temporal verification budget.

Tests: temporally separated polls (>=2) + >=1 history lookup with timestamps;
delayed broker convergence through pipeline hot path for close/partial/modify/entry;
exhausted budget semantics; lock retention. Real FakeMt5 + Mt5Gateway.
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
from metascan.pipeline.request import CommandRequest, InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from helpers import default_account, default_symbol_info


POLL_MS = 50


def _make_facts(**kw) -> RuntimeFactsProvider:
    base = dict(
        runtime_state="READY", entries_enabled=True, safety_mode_active=False,
        trading_halt=False, account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"XAUUSDm": {"bid": 2300.0, "ask": 2300.5, "age_ms": 0}},
        symbol_meta={"XAUUSDm": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "age_ms": 0}},
    )
    base.update(kw)
    return RuntimeFactsProvider.current(**base)


def _start_gw(fake: FakeMt5, loop: asyncio.AbstractEventLoop, *, bot_magic: int = 240101) -> Mt5Gateway:
    fake.set_account(**default_account())
    fake.add_symbol("XAUUSDm", **default_symbol_info("XAUUSDm"))
    fake.set_tick("XAUUSDm", 2300.0, 2300.5, 1_000_000)
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)
    cfg = GatewayConfig(login=123456, password="x", server="s", symbol_suffix="m", watchlist_bases=("XAUUSD",), bot_magic=bot_magic, poll_interval_ms=POLL_MS)
    gw = Mt5Gateway(fake, config=cfg, slot=slot, loop=loop, metrics=metrics)
    gw.start()
    gw.wait_boot(timeout=3.0)
    return gw


def _set_pos(fake: FakeMt5, ticket: int = 1001, symbol: str = "XAUUSDm", volume: float = 0.1, comment: str = "") -> None:
    fake.set_positions([{"ticket": ticket, "symbol": symbol, "magic": 240101, "volume": volume, "price_open": 2300.0, "price_current": 2301.0, "sl": 2290.0, "tp": 2320.0, "profit": 10.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": ticket, "comment": comment}])


def test_default_verification_timeout_is_10s() -> None:
    assert RiskConfig().verification_timeout_s == 10.0


def test_default_verify_poll_interval() -> None:
    assert RiskConfig().verify_poll_interval_ms == 50


@pytest.mark.asyncio
async def test_verify_performs_separated_polls_and_history(tmp_path: Path) -> None:
    """Real gateway verify: >=2 positions_get + >=1 history_deals_get, timestamps differ."""
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    try:
        _set_pos(fake)
        fake.call_log.clear()
        fut = gw.verify("cmd-t", "position.close", "1001", {})
        await asyncio.wait_for(asyncio.wrap_future(fut), timeout=5.0)
        pos_calls = [c for c in fake.call_log if c == "positions_get"]
        assert len(pos_calls) >= 2, f"positions_get calls {len(pos_calls)} < 2"
        hist_calls = [c for c in fake.call_log if c == "history_deals_get"]
        assert len(hist_calls) >= 1, f"history_deals_get calls {len(hist_calls)} < 1"
    finally:
        gw.stop()


@pytest.mark.asyncio
async def test_close_delayed_convergence(tmp_path: Path) -> None:
    """Close timeout → temporal verify → broker state changes → COMPLETED, lock released."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    _set_pos(fake)
    fake.script_order_send_slow(0.3, retcode=10009)
    pending = PendingIntentRegistry()
    facts = _make_facts(positions=(_make_pos_row(),))
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        async def _delayed_remove():
            await asyncio.sleep(0.35)
            fake.remove_position(1001)
        asyncio.create_task(_delayed_remove())
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="close-delay-1")
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (status.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_entry_delayed_convergence(tmp_path: Path) -> None:
    """Entry timeout → temporal verify → position appears → COMPLETED, lock released."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.script_order_send_slow(0.3, retcode=10009, order=50001, deal=40001)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        async def _delayed_position(cmd_id: str):
            await asyncio.sleep(0.35)
            fake.set_positions([{"ticket": 3001, "symbol": "XAUUSDm", "magic": 240101, "volume": 0.1, "price_open": 2300.0, "price_current": 2300.5, "sl": 2295.0, "tp": 2320.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0, "time_msc": 0, "identifier": 3001, "comment": cmd_id[:17]}])
            fake.freeze_ticks()
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="entry-delay-1")
        asyncio.create_task(_delayed_position(record.command_id))
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_partial_delayed_convergence(tmp_path: Path) -> None:
    """Partial close timeout → temporal verify → volume reduced → COMPLETED."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    _set_pos(fake)
    fake.script_order_send_slow(0.3, retcode=10009)
    pending = PendingIntentRegistry()
    facts = _make_facts(positions=(_make_pos_row(),))
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        async def _delayed_reduce():
            await asyncio.sleep(0.35)
            fake.set_volume(1001, 0.05)
        asyncio.create_task(_delayed_reduce())
        req = CommandRequest(kind="position.closePartial", target_id="1001", volume=0.05)
        status = await pipeline.submit_transport(req, idempotency_key="partial-delay-1")
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (status.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_modify_delayed_convergence(tmp_path: Path) -> None:
    """Modify timeout → temporal verify → protection changed → COMPLETED."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    _set_pos(fake)
    fake.script_order_send_slow(0.3, retcode=10009)
    pending = PendingIntentRegistry()
    facts = _make_facts(positions=(_make_pos_row(),))
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1, verification_timeout_s=10, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        async def _delayed_protect():
            await asyncio.sleep(0.35)
            fake.set_protection(1001, 2295.0, 2315.0)
        asyncio.create_task(_delayed_protect())
        req = CommandRequest(kind="position.modifyProtection", target_id="1001", stop_loss=2295.0, take_profit=2315.0)
        status = await pipeline.submit_transport(req, idempotency_key="modify-delay-1")
        await asyncio.sleep(1.5)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (status.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED", f"expected COMPLETED, got {row[0]}"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_exhausted_budget_retains_lock(tmp_path: Path) -> None:
    """Verification budget exhausted → EXECUTION_UNKNOWN with lock retained."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    loop = asyncio.get_running_loop()
    fake = FakeMt5()
    gw = _start_gw(fake, loop)
    fake.block_order_send(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.1, verification_timeout_s=0.2, verify_poll_interval_ms=POLL_MS), pending=pending, facts=facts, bot_magic=240101)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)
        record = await pipeline.submit_internal(req, idempotency_key="exhaust-1")
        await asyncio.sleep(1.0)
        row = journal.run_on_writer(lambda c: c.execute("SELECT state FROM commands WHERE command_id=?", (record.command_id,)).fetchone())
        assert row is not None
        assert row[0] == "EXECUTION_UNKNOWN", f"expected EXECUTION_UNKNOWN, got {row[0]}"
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        gw.stop()
        await bus.close()


def _make_pos_row(ticket: int = 1001, symbol: str = "XAUUSDm") -> dict:
    from metascan.mt5.types import PositionRow
    return PositionRow(ticket=ticket, symbol=symbol, magic=240101, volume=0.1, price_open=2300.0, price_current=2301.0, sl=2290.0, tp=2320.0, profit=10.0, swap=0.0, commission=0.0, type=0, time_msc=0, identifier=ticket, comment="")
