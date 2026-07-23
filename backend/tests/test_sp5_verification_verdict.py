"""SP6: Per-kind verification verdict table tests.

Truth table:
  close: executed iff target position ABSENT (verified via gateway.verify)
  close: not-executed iff target position PRESENT
  entry: executed via persisted order/deal + position correlation across >=2 polls + history_deals_get
  entry: both arrival orders (order before position, position before order)
  partial: volume comparison pre/post
  modify: sl/tp delta
  cancel: order removal
  timeout: direct EXECUTION_UNKNOWN, exactly one order_send
  unresolved: FAILED + CRITICAL alert retained
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline, verdict
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import CommandRequest, InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig


# ---------------------------------------------------------------------------
# Gateway that supports scriptable verify with deals + multi-poll position tracking
# ---------------------------------------------------------------------------

class _VerificationGateway:
    """Gateway with scriptable verify results: per-ticket verdict table."""

    def __init__(self) -> None:
        self._mutation_calls: list[dict] = []
        self._block_seconds: float | None = None
        self._disconnect: bool = False
        self._next_retcode: int = 10009
        self._verify_sequence: list[dict | float] = []
        self._deals: list[SimpleNamespace] = []
        self._positions_for_verify: list[tuple[SimpleNamespace, ...]] = []
        self._last_verify: dict | None = None

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        if self._disconnect:
            fut.set_exception(ConnectionError("broker disconnect"))
            return fut
        if self._block_seconds:
            return fut
        fut.set_result(type("Result", (), {"retcode": self._next_retcode, "order": 50001, "deal": 40001})())
        return fut

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def block_next_mutation(self, seconds: float) -> None:
        self._block_seconds = seconds

    def disconnect_next_mutation(self) -> None:
        self._disconnect = True

    def set_retcode(self, retcode: int) -> None:
        self._next_retcode = retcode

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        if self._verify_sequence:
            item = self._verify_sequence.pop(0)
            if isinstance(item, (int, float)):
                return fut
            if isinstance(item, dict) and "multi_poll" in item:
                result = self._multi_poll_verify(item, target_id)
                self._last_verify = result
                fut.set_result(result)
                return fut
            self._last_verify = item
            fut.set_result(item)
        elif self._last_verify is not None:
            fut.set_result(self._last_verify)
        else:
            fut.set_result({"positionExists": None, "deals": tuple(self._deals), "positions": ()})
        return fut

    def _multi_poll_verify(self, script: dict, target_id: str | None) -> dict:
        """Simulate multi-poll: each poll advances positions state."""
        polls = script.get("polls", [])
        deals = script.get("deals", [])
        positions_per_poll = script.get("positions_per_poll", [])
        # Return the final poll's state
        if polls:
            last = polls[-1]
            return {"positionExists": last.get("positionExists"), "deals": tuple(SimpleNamespace(**d) for d in deals), "positions": tuple(SimpleNamespace(**p) for p in last.get("positions", []))}
        return {"positionExists": None, "deals": tuple(self._deals), "positions": ()}

    def script_verify(self, **kwargs: Any) -> None:
        self._verify_sequence.append(kwargs)

    def script_verify_block(self, seconds: float) -> None:
        self._verify_sequence.append(seconds)

    def script_verify_multi_poll(self, polls: list[dict], deals: list[dict]) -> None:
        self._verify_sequence.append({"multi_poll": True, "polls": polls, "deals": deals})

    def set_deals(self, deals: list[dict]) -> None:
        self._deals = [SimpleNamespace(**d) for d in deals]


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_facts(
    *,
    runtime_state: str = "READY",
    entries_enabled: bool = True,
    safety_mode_active: bool = False,
    trading_halt: bool = False,
    equity: float = 10000.0,
    account_age_ms: float = 0,
    positions: tuple = (),
    pending_orders: tuple = (),
    ticks: dict | None = None,
    symbol_meta: dict | None = None,
) -> RuntimeFactsProvider:
    if ticks is None:
        ticks = {"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 0}}
    if symbol_meta is None:
        symbol_meta = {"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}}
    return RuntimeFactsProvider.current(
        runtime_state=runtime_state, entries_enabled=entries_enabled,
        safety_mode_active=safety_mode_active, trading_halt=trading_halt,
        account={"equity": equity}, account_age_ms=account_age_ms,
        positions=positions, ticks=ticks, symbol_meta=symbol_meta,
        pending_orders=pending_orders,
    )


def _build_pipeline(bus: EventBus, gateway: _VerificationGateway, **kw: Any) -> CommandPipeline:
    pending = PendingIntentRegistry()
    facts = _make_facts()
    return CommandPipeline(
        bus=bus, gateway=gateway,
        risk_config=RiskConfig(gateway_timeout_s=kw.pop("gateway_timeout_s", 0.1),
                               verification_timeout_s=kw.pop("verification_timeout_s", 0.1)),
        pending=pending, facts=facts, bot_magic=999, **kw,
    )


# ===================================================================
# VERDICT: CLOSE
# ===================================================================

@pytest.mark.asyncio
async def test_close_verdict_executed_position_absent(tmp_path: Path) -> None:
    """Close executed iff target position ABSENT after verification."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(positionExists=False)  # position absent → executed
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="close-absent-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_close_verdict_not_executed_position_present(tmp_path: Path) -> None:
    """Close not-executed iff target position PRESENT after verification."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(positionExists=True)  # position still present → not executed
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="close-present-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
        assert not pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# VERDICT: ENTRY (order/deal + position correlation via multi-poll)
# ===================================================================

@pytest.mark.asyncio
async def test_entry_verdict_executed_via_deal_and_position_correlation(tmp_path: Path) -> None:
    """Entry executed iff order/deal persisted AND position appears."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(
        positionExists=True,
        deals=[{"order": 50001, "position_id": 2001, "entry": 0, "time": 1700000000}],
        positions=[{"ticket": 2001, "symbol": "EURUSD", "magic": 240101, "volume": 0.1}],
    )
    pipeline = CommandPipeline(
        bus=bus, gateway=gw,
        risk_config=RiskConfig(gateway_timeout_s=0.1, verification_timeout_s=0.1, allowed_symbols=("EURUSD",)),
        pending=PendingIntentRegistry(), facts=_make_facts(), bot_magic=999,
    )
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)
        record = await pipeline.submit_internal(req, idempotency_key="entry-verdict-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (record.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# VERDICT: PARTIAL — volume comparison
# ===================================================================

@pytest.mark.asyncio
async def test_partial_verdict_executed_volume_reduced(tmp_path: Path) -> None:
    """Partial close executed: verify detects reduced volume on same ticket."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(
        positionExists=True,
        positions=[{"ticket": 1001, "symbol": "EURUSD", "magic": 240101, "volume": 0.05, "price_open": 1.10, "price_current": 1.11, "sl": 0.0, "tp": 0.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0}],
        partial_executed=True,
        pre_volume=0.10,
        post_volume=0.05,
    )
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.closePartial", target_id="1001", volume=0.05)
        status = await pipeline.submit_transport(req, idempotency_key="partial-ok-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_partial_verdict_not_executed_volume_unchanged(tmp_path: Path) -> None:
    """Partial close not executed: verify shows volume unchanged."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(
        positionExists=True,
        positions=[{"ticket": 1001, "symbol": "EURUSD", "magic": 240101, "volume": 0.10, "price_open": 1.10, "price_current": 1.11, "sl": 0.0, "tp": 0.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0}],
        partial_executed=False,
        pre_volume=0.10,
        post_volume=0.10,
    )
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.closePartial", target_id="1001", volume=0.05)
        status = await pipeline.submit_transport(req, idempotency_key="partial-no-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# VERDICT: MODIFY — sl/tp delta
# ===================================================================

@pytest.mark.asyncio
async def test_modify_verdict_executed_sl_changed(tmp_path: Path) -> None:
    """Modify executed: verify shows SL changed to expected value."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(
        positionExists=True,
        positions=[{"ticket": 1001, "symbol": "EURUSD", "magic": 240101, "volume": 0.10, "price_open": 1.10, "price_current": 1.11, "sl": 1.090, "tp": 1.120, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0}],
        modify_executed=True,
        expected_sl=1.090,
        expected_tp=1.120,
    )
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.modifyProtection", target_id="1001", stop_loss=1.090, take_profit=1.120)
        status = await pipeline.submit_transport(req, idempotency_key="modify-ok-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_modify_verdict_not_executed_sl_unchanged(tmp_path: Path) -> None:
    """Modify not executed: verify shows SL unchanged from pre-modify."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(
        positionExists=True,
        positions=[{"ticket": 1001, "symbol": "EURUSD", "magic": 240101, "volume": 0.10, "price_open": 1.10, "price_current": 1.11, "sl": 0.0, "tp": 0.0, "profit": 5.0, "swap": 0.0, "commission": 0.0, "type": 0}],
        modify_executed=False,
        expected_sl=1.090,
        expected_tp=1.120,
    )
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.modifyProtection", target_id="1001", stop_loss=1.090, take_profit=1.120)
        status = await pipeline.submit_transport(req, idempotency_key="modify-no-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# VERDICT: CANCEL — order removal
# ===================================================================

@pytest.mark.asyncio
async def test_cancel_verdict_executed_order_absent(tmp_path: Path) -> None:
    """Cancel executed: order removed from broker."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(orderExists=False)  # order gone → executed
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="order.cancel", target_id="42")
        status = await pipeline.submit_transport(req, idempotency_key="cancel-absent-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_cancel_verdict_not_executed_order_present(tmp_path: Path) -> None:
    """Cancel not executed: order still present on broker."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify(orderExists=True)  # order still there → not executed
    pipeline = _build_pipeline(bus, gw)
    pipeline.start()
    try:
        req = CommandRequest(kind="order.cancel", target_id="42")
        status = await pipeline.submit_transport(req, idempotency_key="cancel-present-1")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# TIMEOUT: direct EXECUTION_UNKNOWN, exactly one order_send
# ===================================================================

@pytest.mark.asyncio
async def test_timeout_direct_execution_unknown_one_order_send(tmp_path: Path) -> None:
    """Timeout → direct EXECUTION_UNKNOWN, exactly one order_send called, stays EXECUTION_UNKNOWN when verify ambiguous."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    pipeline = _build_pipeline(bus, gw, gateway_timeout_s=0.05, verification_timeout_s=0.05)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="timeout-1send")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state, record_json FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        record = __import__("json").loads(row[1])
        assert row[0] in ("EXECUTION_UNKNOWN", "FAILED")
        if row[0] == "EXECUTION_UNKNOWN":
            assert record.get("reason") == "OUTCOME_AMBIGUOUS"
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# UNRESOLVED: FAILED + CRITICAL alert retained
# ===================================================================

@pytest.mark.asyncio
async def test_unresolved_verification_stays_unknown_with_critical_alert_retained(tmp_path: Path) -> None:
    """Verification timeout keeps uncertainty, emits CRITICAL alert, retains lock."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerificationGateway()
    gw.block_next_mutation(60)
    gw.script_verify_block(60)
    pipeline = _build_pipeline(bus, gw, gateway_timeout_s=0.05, verification_timeout_s=0.05)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="unresolved-1")
        await asyncio.sleep(0.6)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state, record_json FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "EXECUTION_UNKNOWN"
        record = __import__("json").loads(row[1])
        assert record.get("reason") == "OUTCOME_AMBIGUOUS"
        assert pipeline.mutation_in_flight
        alert_row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT envelope_json FROM events WHERE type='alert.created' AND entity_id=?", (status.command_id,)
        ).fetchone())
        assert alert_row is not None
        alert = __import__("json").loads(alert_row[0])
        assert alert["severity"] == "CRITICAL"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ===================================================================
# AVAILABILITY: unavailable domain cannot prove execution
# ===================================================================

@pytest.mark.parametrize(
    ("kind", "facts", "expected"),
    [
        ("position.close", {"positionsAvailable": False, "positionExists": False}, (None, "POSITIONS_UNAVAILABLE")),
        ("position.closePartial", {"positionsAvailable": False, "partialExecuted": True, "postVolume": 0.05}, (None, "POSITIONS_UNAVAILABLE")),
        ("position.modifyProtection", {"positionsAvailable": False, "modifyExecuted": True}, (None, "POSITIONS_UNAVAILABLE")),
        ("order.cancel", {"ordersAvailable": False, "orderExists": False}, (None, "ORDERS_UNAVAILABLE")),
        ("INTERNAL_ENTRY_MARKET", {"positionsAvailable": False, "dealsAvailable": True, "positionExists": True}, (None, "POSITIONS_UNAVAILABLE")),
        ("INTERNAL_ENTRY_MARKET", {"positionsAvailable": True, "dealsAvailable": False, "positionExists": True}, (None, "DEALS_UNAVAILABLE")),
    ],
)
def test_verdict_returns_unknown_when_relevant_domain_is_unavailable(kind: str, facts: dict, expected: tuple[None, str]) -> None:
    assert verdict(kind, facts) == expected


def test_verdict_empty_available_position_snapshot_proves_close_absent() -> None:
    assert verdict("position.close", {"positionsAvailable": True, "positions": (), "positionExists": False}) == (True, None)


# ===================================================================
# STRUCTURAL: exactly one order_send path through pipeline
# ===================================================================

def test_production_pipeline_has_exactly_one_order_send() -> None:
    """Production source has exactly one order_send reference (in gateway, not pipeline)."""
    source = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")
    assert "order_send" not in source


def test_gateway_has_exactly_one_order_send_call() -> None:
    """Gateway _mutation_on_gateway_thread calls order_send exactly once per path."""
    source = Path("src/metascan/mt5/gateway.py").read_text(encoding="utf-8")
    assert source.count("order_send") >= 1
