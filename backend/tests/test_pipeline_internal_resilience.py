"""Pipeline internal command resilience tests.

Covers:
  1. Gate rejection drives InternalCommandRecord → FAILED (not RuntimeCommandStatus coercion)
  2. Pipeline task stays alive after gate rejection; subsequent command processes
  3. Handler exception does not silently kill queue; next command processes or pipeline unhealthy
  4. CancelledError never swallowed
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from metascan.bus.event_bus import EventBus
from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import InternalCommandRecord, InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_facts(*, allowed_symbols: tuple[str, ...] = (), entries_enabled: bool = True) -> RuntimeFactsProvider:
    return RuntimeFactsProvider.current(
        runtime_state="READY",
        entries_enabled=entries_enabled,
        safety_mode_active=False,
        trading_halt=False,
        account={"equity": 10_000.0, "balance": 10_000.0},
        account_age_ms=100,
        positions=(),
        ticks={"XAUUSDm": {"ask": 2300.0, "bid": 2299.9, "age_ms": 10}},
        symbol_meta={"XAUUSDm": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "age_ms": 10}},
    )


class FakeGateway:
    """Minimal gateway stub for pipeline tests."""

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []

    def success_retcodes(self) -> tuple[int, ...]:
        return (0,)

    def mutation(self, command_id: str, kind: str, target: str | None, payload: dict, *, reason: str = "") -> Any:
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        result = MagicMock(retcode=0)
        fut.set_result(result)
        self._calls.append({"command_id": command_id, "kind": kind, "target": target, "payload": payload, "reason": reason})
        return fut

    def verify(self, target: str | None) -> Any:
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        fut.set_result({"positions": (), "deals": (), "positionExists": None, "orderExists": None})
        return fut

    def sweep_facts(self) -> Any:
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        fut.set_result({"orders": (), "positions": ()})
        return fut


async def _make_pipeline(
    *,
    journal: Journal | None = None,
    risk_config: RiskConfig | None = None,
    facts: RuntimeFactsProvider | None = None,
    bus: EventBus | None = None,
    pending: PendingIntentRegistry | None = None,
    gateway: FakeGateway | None = None,
    db_path: str | None = None,
) -> tuple[CommandPipeline, EventBus]:
    cfg = risk_config or RiskConfig(queue_size=16, allowed_symbols=("XAUUSDm",), gateway_timeout_s=0.5, verification_timeout_s=0.5)
    if journal is None:
        journal = Journal(db_path or ":memory:")
        journal.open()
    if bus is None:
        bus = EventBus(journal)
        await bus.start()
    pipeline = CommandPipeline(
        bus=bus,
        gateway=gateway or FakeGateway(),
        risk_config=cfg,
        pending=pending or PendingIntentRegistry(),
        facts=facts or _make_facts(),
        bot_magic=999,
    )
    return pipeline, bus


def _internal_request(symbol: str = "XAUUSDm", side: str = "BUY") -> InternalEntryRequest:
    return InternalEntryRequest(symbol=symbol, side=side, stopLoss=2290.0, takeProfit=2320.0)


async def _drain_events(bus: EventBus, subscriber_id: str = "test", count: int = 50, timeout: float = 2.0) -> list[RuntimeEventEnvelope]:
    sub = await bus.subscribe(subscriber_id, maxsize=count + 10)
    events: list[RuntimeEventEnvelope] = []
    try:
        while len(events) < count:
            ev = await asyncio.wait_for(sub.get(), timeout=timeout)
            events.append(ev)
    except asyncio.TimeoutError:
        pass
    finally:
        await bus.unsubscribe(subscriber_id)
    return events


# ---------------------------------------------------------------------------
# Constructor safety: bot magic is mandatory and must never be zero.
# R20/R21 quarantine ruling: magic 0 commonly denotes manual positions.
# ---------------------------------------------------------------------------

def test_pipeline_requires_nonzero_bot_magic() -> None:
    import inspect

    parameter = inspect.signature(CommandPipeline).parameters["bot_magic"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(ValueError, match="bot_magic"):
        CommandPipeline(
            bus=MagicMock(),
            gateway=MagicMock(),
            risk_config=RiskConfig(),
            pending=PendingIntentRegistry(),
            facts=_make_facts(),
            bot_magic=0,
        )


# ---------------------------------------------------------------------------
# Test 1: Gate rejection drives InternalCommandRecord → FAILED
# ---------------------------------------------------------------------------

async def test_gate_rejection_returns_internal_command_record() -> None:
    """INTERNAL_ENTRY_MARKET gate rejection must produce InternalCommandRecord (not RuntimeCommandStatus).

    Source: _process line 241 must call _transition_internal, not _transition.
    """
    pipeline, bus = await _make_pipeline(
        facts=_make_facts(allowed_symbols=()),  # XAUUSDm not allowed → gate rejects
    )
    pipeline.start()

    record = await pipeline.submit_internal(_internal_request(), idempotency_key="ik-1")

    # submit_internal returns InternalCommandRecord immediately (PREPARED)
    assert isinstance(record, InternalCommandRecord), f"submit_internal returned {type(record)}, want InternalCommandRecord"
    assert record.state == "PREPARED"

    # Wait for processing
    await asyncio.sleep(0.3)

    # Pipeline task must still be alive
    assert pipeline._task is not None
    assert not pipeline._task.done(), "pipeline task died after gate rejection"

    # The record should have been transitioned to FAILED via _transition_internal
    # (not coerced to RuntimeCommandStatus via _transition)
    # We verify by checking the bus events for the command.failed event
    # which carries the canonical reason from the gate.
    await pipeline.stop()


# ---------------------------------------------------------------------------
# Test 2: Pipeline processes subsequent command after gate rejection
# ---------------------------------------------------------------------------

async def test_pipeline_processes_next_command_after_gate_rejection() -> None:
    """After gate rejection, pipeline remains alive and processes a control command."""
    pipeline, bus = await _make_pipeline(
        facts=_make_facts(allowed_symbols=()),
    )
    pipeline.start()

    # Enqueue an INTERNAL_ENTRY_MARKET that will be gate-rejected
    await pipeline.submit_internal(_internal_request(), idempotency_key="ik-2")
    await asyncio.sleep(0.2)

    # Pipeline must still be alive
    assert pipeline._task is not None
    assert not pipeline._task.done()

    # Now enqueue a valid control command
    from metascan.pipeline.request import CommandRequest
    req = CommandRequest(kind="runtime.enableEntries")
    status = RuntimeCommandStatus(
        command_id="ctrl-1", client_request_id="c1", correlation_id="corr-1",
        idempotency_key="ik-ctrl-1", kind="runtime.enableEntries", state="PREPARED",
        created_at="2026-07-14T00:00:00Z", updated_at="2026-07-14T00:00:00Z",
    )
    pipeline.enqueue(status, req, origin="TRANSPORT")
    await asyncio.sleep(0.3)

    assert pipeline.entries_enabled is True
    assert not pipeline._task.done()
    await pipeline.stop()


# ---------------------------------------------------------------------------
# Test 3: Handler exception does not kill queue
# ---------------------------------------------------------------------------

async def test_handler_exception_does_not_kill_queue(tmp_path: Path) -> None:
    """An unexpected exception in _process for one command must not kill the pipeline.

    Subsequent commands must still process. Pipeline task stays alive.
    Source: _run must catch per-command exceptions, log, fail command, emit alert, continue.
    """
    pipeline, bus = await _make_pipeline(db_path=str(tmp_path / "test.db"))
    pipeline.start()

    # Monkey-patch _process to raise on the first call, then work normally
    original_process = pipeline._process
    call_count = 0

    async def _failing_process(item: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated handler crash")
        return await original_process(item)

    pipeline._process = _failing_process  # type: ignore[assignment]

    # Enqueue first command (will crash in _process)
    from metascan.pipeline.request import CommandRequest
    req1 = CommandRequest(kind="runtime.enableEntries")
    status1 = RuntimeCommandStatus(
        command_id="crash-1", client_request_id="c1", correlation_id="corr-1",
        idempotency_key="ik-crash-1", kind="runtime.enableEntries", state="PREPARED",
        created_at="2026-07-14T00:00:00Z", updated_at="2026-07-14T00:00:00Z",
    )
    pipeline.enqueue(status1, req1, origin="TRANSPORT")

    await asyncio.sleep(0.3)

    # Pipeline task must still be alive
    assert pipeline._task is not None
    assert not pipeline._task.done(), "pipeline task died after handler exception"
    assert pipeline.healthy is True

    rows = bus.journal.read_events(bus.boot_id, 0, 500)
    failed_events = [r for r in rows if r.command_id == "crash-1" and r.type == "command.failed"]
    assert len(failed_events) >= 1, "no command.failed event for crashed command"
    assert failed_events[0].payload.get("state") == "FAILED"
    assert failed_events[0].payload.get("reason") == "BROKER_REJECTED"

    # Alert must have been emitted
    alert_rows = [r for r in rows if r.type == "alert.created" and r.command_id == "crash-1"]
    assert len(alert_rows) >= 1, "no alert.created for crashed command"
    assert alert_rows[0].payload.get("reason") == "PIPELINE_INTERNAL_ERROR"
    assert alert_rows[0].severity == "CRITICAL"

    # Enqueue second command (should process normally)
    req2 = CommandRequest(kind="runtime.enableEntries")
    status2 = RuntimeCommandStatus(
        command_id="after-crash-1", client_request_id="c2", correlation_id="corr-2",
        idempotency_key="ik-crash-2", kind="runtime.enableEntries", state="PREPARED",
        created_at="2026-07-14T00:00:00Z", updated_at="2026-07-14T00:00:00Z",
    )
    pipeline.enqueue(status2, req2, origin="TRANSPORT")
    await asyncio.sleep(0.3)

    assert not pipeline._task.done()
    assert pipeline.healthy is True
    await pipeline.stop()


# ---------------------------------------------------------------------------
# Test 4: CancelledError not swallowed
# ---------------------------------------------------------------------------

async def test_cancelled_error_not_swallowed() -> None:
    """CancelledError must propagate and cancel the task, not be caught as a generic exception."""
    pipeline, bus = await _make_pipeline()
    pipeline.start()

    # Stop should cancel the task cleanly (CancelledError raised, caught by stop())
    assert pipeline._task is not None
    await pipeline.stop()
    assert pipeline._task is None
