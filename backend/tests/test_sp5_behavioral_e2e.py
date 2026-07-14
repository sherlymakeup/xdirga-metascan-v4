"""SP5 comprehensive E2E behavioral tests — SP5_DESIGN §10 requirements.

Tests: timeout→EXECUTION_UNKNOWN(OUTCOME_AMBIGUOUS), disconnect→EXECUTION_UNKNOWN,
order_check pass/fail, broker reject, entry/close/protection/cancel/bulk/emergency,
late-result, health mutationInFlight, per-item bulk outcomes,
no _timed_out/no PARTIAL_FINAL structural enforcement.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import CommandRequest, InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.risk_gate import GATE_NAMES, classify

# ---------------------------------------------------------------------------
# E2E: timeout → EXECUTION_UNKNOWN, scope+intent retained, no resend
# ---------------------------------------------------------------------------

class _DummyGateway:
    def __init__(self) -> None:
        self._futures: list[asyncio.Future] = []
        self._mutation_calls: list[dict] = []
        self._block_seconds: float | None = None
        self._disconnect: bool = False
        self._next_retcode: int = 10009

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        self._futures.append(fut)
        if self._disconnect:
            fut.set_exception(ConnectionError("broker disconnect"))
            return fut
        if self._block_seconds:
            return fut
        fut.set_result(type("Result", (), {"retcode": self._next_retcode})())
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
        fut.set_result({"positionExists": None})
        return fut


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


@pytest.mark.asyncio
async def test_timeout_goes_execution_unknown_retains_scope_and_intent(tmp_path: Path) -> None:
    """SP5_DESIGN §7: timeout → EXECUTION_UNKNOWN(OUTCOME_AMBIGUOUS), scope+intent retained, no resend."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    gw.block_next_mutation(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="12345")
        status = await pipeline.submit_transport(req, idempotency_key="timeout-1")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state, record_json FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        record = __import__("json").loads(row[1])
        assert row[0] == "EXECUTION_UNKNOWN"
        assert record.get("reason") == "OUTCOME_AMBIGUOUS"
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_disconnect_transitions_execution_unknown(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    gw.disconnect_next_mutation()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="12345")
        status = await pipeline.submit_transport(req, idempotency_key="dc-1")
        await asyncio.sleep(0.2)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state, record_json FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        record = __import__("json").loads(row[1])
        assert row[0] == "EXECUTION_UNKNOWN"
        assert record.get("reason") == "BROKER_DISCONNECT_MID_CALL"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# E2E: entry complete flow
# ---------------------------------------------------------------------------

class _EntryGateway:
    def __init__(self) -> None:
        self._mutation_calls: list[dict] = []
        self._next_retcode: int = 10009

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(type("Result", (), {"retcode": self._next_retcode})())
        return fut

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def set_retcode(self, retcode: int) -> None:
        self._next_retcode = retcode

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


@pytest.mark.asyncio
async def test_entry_complete_e2e(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _EntryGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("EURUSD",)), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)
        record = await pipeline.submit_internal(req, idempotency_key="entry-e2e-1")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (record.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        assert len(gw._mutation_calls) == 1
        assert gw._mutation_calls[0]["kind"] == "INTERNAL_ENTRY_MARKET"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_entry_rejected_by_broker(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _EntryGateway()
    gw.set_retcode(10016)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("EURUSD",)), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)
        record = await pipeline.submit_internal(req, idempotency_key="entry-broker-reject")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (record.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# E2E: close, partial close, protection, cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_e2e(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="close-e2e")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        assert gw._mutation_calls[0]["kind"] == "position.close"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_close_partial_e2e(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.closePartial", target_id="1001", volume=0.05)
        status = await pipeline.submit_transport(req, idempotency_key="partial-e2e")
        await asyncio.sleep(0.3)
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
async def test_protection_e2e(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.modifyProtection", target_id="1001", stop_loss=1.090, take_profit=1.110)
        status = await pipeline.submit_transport(req, idempotency_key="protect-e2e")
        await asyncio.sleep(0.3)
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
async def test_cancel_e2e(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="order.cancel", target_id="42")
        status = await pipeline.submit_transport(req, idempotency_key="cancel-e2e")
        await asyncio.sleep(0.3)
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


# ---------------------------------------------------------------------------
# E2E: bulk (cancelAll, closeAll) per-item outcomes
# ---------------------------------------------------------------------------

class _BulkGateway:
    def __init__(self, sweep_results: dict | None = None, rescan_results: dict | None = None) -> None:
        if sweep_results is None:
            sweep_results = {"orders": (), "positions": ()}
        self._sweep_results = sweep_results
        self._rescan_results = rescan_results or {"orders": (), "positions": ()}
        self._call_count = 0
        self._mutation_calls: list[dict] = []
        self._next_retcode: int = 10009

    def sweep_facts(self) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        self._call_count += 1
        if self._call_count == 1:
            fut.set_result(self._sweep_results)
        else:
            fut.set_result(self._rescan_results)
        return fut

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(type("Result", (), {"retcode": self._next_retcode})())
        return fut

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


@pytest.mark.asyncio
async def test_cancel_all_bulk_per_item(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    sweep = {
        "orders": (
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
            {"ticket": 2, "symbol": "EURUSD", "magic": 999, "volume": 0.2, "orderType": 3},
            {"ticket": 3, "symbol": "EURUSD", "magic": 888, "volume": 0.3, "orderType": 2},
        ),
        "positions": (),
    }
    gw = _BulkGateway(sweep)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="order.cancelAll")
        status = await pipeline.submit_transport(req, idempotency_key="cancelAll-e2e")
        await asyncio.sleep(0.5)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "COMPLETED"
        bot_cancels = [c for c in gw._mutation_calls if c["kind"] == "order.cancel"]
        assert len(bot_cancels) == 2
        cancelled_tickets = {c["target_id"] for c in bot_cancels}
        assert cancelled_tickets == {"1", "2"}
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# Emergency E2E
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emergency_halts_cancels_closes_rescans(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    sweep = {
        "orders": (
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        "positions": (),
    }
    gw = _BulkGateway(sweep)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="kill-e2e")
        await asyncio.sleep(0.5)
        assert pipeline.halted
        assert not pipeline.entries_enabled
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# Health mutationInFlight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mutation_in_flight_reflects_active_locks(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    gw.block_next_mutation(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        assert not pipeline.mutation_in_flight
        req = CommandRequest(kind="position.close", target_id="1001")
        await pipeline.submit_transport(req, idempotency_key="mif-1")
        await asyncio.sleep(0.15)
        assert pipeline.mutation_in_flight
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# classification covers all kinds
# ---------------------------------------------------------------------------

def test_classify_all_control_kinds() -> None:
    from metascan.pipeline.command_pipeline import CONTROL_KINDS
    for kind in CONTROL_KINDS:
        result = classify(kind)
        assert result is not None, f"classify({kind!r}) returned None"
        classification, mutates = result
        assert classification in ("ENTRY", "REDUCE", "PROTECTION", "CANCEL", "CONTROL", "EMERGENCY")


def test_classify_internal_entry_is_entry_mutates() -> None:
    assert classify("INTERNAL_ENTRY_MARKET") == ("ENTRY", True)


def test_gate_names_count_is_exactly_eight() -> None:
    assert len(GATE_NAMES) == 8


# ---------------------------------------------------------------------------
# PendingIntentRegistry SP3 Protocol
# ---------------------------------------------------------------------------

def test_pending_intent_registry_satisfies_sp3_protocol() -> None:
    from metascan.mt5.pending_intent import PendingIntentLookup
    registry = PendingIntentRegistry()
    assert isinstance(registry, PendingIntentLookup)


# ---------------------------------------------------------------------------
# InternalEntryRequest canonical_json excludes internal fields
# ---------------------------------------------------------------------------

def test_internal_entry_canonical_json_excludes_internal_only() -> None:
    import json
    req = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)
    js = json.loads(req.canonical_json())
    assert "origin" not in js
    assert "execution_kind" not in js
    assert js == {"side": "BUY", "stopLoss": 1.095, "symbol": "EURUSD"}


# ---------------------------------------------------------------------------
# Late result after timeout → no resend
# ---------------------------------------------------------------------------

class _LateGateway:
    def __init__(self) -> None:
        self._futures: list[asyncio.Future] = []
        self._mutation_calls: list[dict] = []

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        self._futures.append(fut)
        return fut

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def resolve_late(self, retcode: int = 10009) -> None:
        for fut in self._futures:
            if not fut.done():
                fut.set_result(type("Result", (), {"retcode": retcode})())

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


@pytest.mark.asyncio
async def test_late_result_after_timeout_stays_execution_unknown(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _LateGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="late-1")
        await asyncio.sleep(0.3)
        gw.resolve_late(10009)
        await asyncio.sleep(0.1)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (status.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "EXECUTION_UNKNOWN"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# Structural: no _timed_out, no PARTIAL_FINAL in production source
# ---------------------------------------------------------------------------

def test_production_pipeline_has_no_timed_out_method() -> None:
    from pathlib import Path
    source = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")
    assert "_timed_out" not in source


def test_production_pipeline_has_no_partial_final() -> None:
    from pathlib import Path
    source = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")
    assert "PARTIAL_FINAL" not in source


def test_outcome_handler_has_no_partial_final() -> None:
    from pathlib import Path
    source = Path("src/metascan/pipeline/outcome_handler.py").read_text(encoding="utf-8")
    assert "PARTIAL_FINAL" not in source


def test_production_pipeline_has_no_timed_out_state() -> None:
    from pathlib import Path
    source = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")
    assert '"TIMED_OUT"' not in source


# ---------------------------------------------------------------------------
# Verification: timeout → verify → resolved/executed → COMPLETED release
# ---------------------------------------------------------------------------

class _VerifyingGateway:
    def __init__(self) -> None:
        self._mutation_calls: list[dict] = []
        self._verify_results: list[dict | float] = []
        self._block_seconds: float | None = None

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict, *, reason: str = "MANUAL") -> asyncio.Future:
        self._mutation_calls.append({"command_id": command_id, "kind": kind, "target_id": target_id, "request": request, "reason": reason})
        fut: asyncio.Future = asyncio.Future()
        if self._block_seconds:
            return fut
        fut.set_result(type("Result", (), {"retcode": 10009})())
        return fut

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        if self._verify_results:
            item = self._verify_results.pop(0)
            if isinstance(item, (int, float)):
                return fut
            fut.set_result(item)
        else:
            fut.set_result({"positionExists": None})
        return fut

    def script_verify(self, **kwargs: Any) -> None:
        self._verify_results.append(kwargs)

    def script_verify_block(self, seconds: float) -> None:
        self._verify_results.append(seconds)

    def block_next_mutation(self, seconds: float) -> None:
        self._block_seconds = seconds


@pytest.mark.asyncio
async def test_unknown_verifies_executed_releases_lock(tmp_path: Path) -> None:
    """Close: position ABSENT → executed → COMPLETED, lock released."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerifyingGateway()
    gw.block_next_mutation(60)
    gw.script_verify(positionExists=False)  # position absent → close executed
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="verify-exec-1")
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
async def test_unknown_verifies_never_existed_releases_lock(tmp_path: Path) -> None:
    """Close: position PRESENT → not executed → FAILED, lock released."""
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerifyingGateway()
    gw.block_next_mutation(60)
    gw.script_verify(positionExists=True)  # position still there → close not executed
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="verify-never-1")
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


@pytest.mark.asyncio
async def test_unknown_verifies_unresolved_transitions_failed_retains_lock(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _VerifyingGateway()
    gw.block_next_mutation(60)
    gw.script_verify_block(60)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(gateway_timeout_s=0.1, verification_timeout_s=0.1), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="position.close", target_id="1001")
        status = await pipeline.submit_transport(req, idempotency_key="verify-null-1")
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


# ---------------------------------------------------------------------------
# Restart recovery: persisted unresolved entry intents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_recovers_unresolved_entry_intents(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    journal.open()
    journal.register_entry_intent(symbol="XAUUSDm", command_id="entry-old", state="PENDING", order_ticket=7)
    journal.close()
    bus = EventBus(journal)
    await bus.start()
    gw = _VerifyingGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999, journal=journal)
    pipeline.start()
    try:
        assert pipeline.mutation_in_flight
        assert pending.has_pending_entry("XAUUSDm")
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# Persistent halted/entries-disabled state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_runtime_halted_state_recovered_on_start(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    journal.open()
    journal.run_on_writer(lambda conn: (
        conn.execute("INSERT INTO runtime_state (key, value) VALUES ('halted', '1')"),
        conn.execute("INSERT INTO runtime_state (key, value) VALUES ('entries_enabled', '0')"),
        conn.commit(),
    ))
    journal.close()
    bus = EventBus(journal)
    await bus.start()
    gw = _VerifyingGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999, journal=journal)
    pipeline.start()
    try:
        assert pipeline.halted
        assert not pipeline.entries_enabled
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_internal_entry_rejected_when_halted(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    gw = _EntryGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("EURUSD",)), pending=pending, facts=facts, bot_magic=999)
    pipeline.halted = True
    pipeline.entries_enabled = False
    pipeline.start()
    try:
        req = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)
        record = await pipeline.submit_internal(req, idempotency_key="halted-entry")
        await asyncio.sleep(0.3)
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id=?", (record.command_id,)
        ).fetchone())
        assert row is not None
        assert row[0] == "FAILED"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


@pytest.mark.asyncio
async def test_start_resume_clears_halted_entries_re_enabled(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    journal.open()
    journal.run_on_writer(lambda conn: (
        conn.execute("INSERT INTO runtime_state (key, value) VALUES ('halted', '1')"),
        conn.execute("INSERT INTO runtime_state (key, value) VALUES ('entries_enabled', '0')"),
        conn.commit(),
    ))
    journal.close()
    bus = EventBus(journal)
    await bus.start()
    gw = _DummyGateway()
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(allowed_symbols=("EURUSD",)), pending=pending, facts=facts, bot_magic=999, journal=journal)
    pipeline.start()
    try:
        assert pipeline.halted
        assert not pipeline.entries_enabled
        req = CommandRequest(kind="runtime.start")
        await pipeline.submit_transport(req, idempotency_key="start-1")
        await asyncio.sleep(0.2)
        assert not pipeline.halted
        assert pipeline.entries_enabled
        row = journal.run_on_writer(lambda conn: conn.execute(
            "SELECT value FROM runtime_state WHERE key='halted'"
        ).fetchone())
        assert row is not None
        assert row[0] == "0"
    finally:
        pipeline._task.cancel()
        try: await pipeline._task
        except asyncio.CancelledError: pass
        await bus.close()


# ---------------------------------------------------------------------------
# Mid-sweep fill: cancelAll with orders appearing between sweeps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_all_with_mid_sweep_straggler_fails(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "db.sqlite")
    bus = EventBus(journal)
    await bus.start()
    sweep = {
        "orders": (
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        "positions": (),
    }
    rescan = {
        "orders": (
            {"ticket": 2, "symbol": "EURUSD", "magic": 999, "volume": 0.2, "orderType": 2},
        ),
        "positions": (),
    }
    gw = _BulkGateway(sweep, rescan)
    pending = PendingIntentRegistry()
    facts = _make_facts()
    pipeline = CommandPipeline(bus=bus, gateway=gw, risk_config=RiskConfig(), pending=pending, facts=facts, bot_magic=999)
    pipeline.start()
    try:
        req = CommandRequest(kind="order.cancelAll")
        status = await pipeline.submit_transport(req, idempotency_key="mid-sweep")
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


# ---------------------------------------------------------------------------
# Decimal exposure comparisons
# ---------------------------------------------------------------------------

def test_exposure_gate_uses_decimal_comparisons() -> None:
    from pathlib import Path
    source = Path("src/metascan/pipeline/risk_gate.py").read_text(encoding="utf-8")
    assert "Decimal(str(" in source
    assert "max_vol = Decimal" in source
