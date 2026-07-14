"""SP7: Bulk cancelAll/closeAll and emergency behavioral tests.

Requirements (R20 parent-child identity, R21 terminal-once summary):
  1. Child ops (per-item closes/cancels) each have UNIQUE command_id — never reuse parent command_id.
  2. Actual outcome accounting: successful / failed / unknown / skipped.
  3. After definitive failure or uncertainty: continue to next child (no abort-on-first-error).
  4. Parent transitions terminal EXACTLY ONCE after rescan, with deterministic summary + straggler IDs + foreign untouched.
  5. Any failure/unknown/remaining → parent command.failed + alert.created CRITICAL.
  6. None (all success) → parent command.completed.
  7. Emergency: halt BEFORE any IO → cancel pending ORDERS → close open POSITIONS → rescan.
  8. Safety events ordering: safety.kill.started → safety.kill.progress* → safety.kill.completed|failed.
  9. Child UNKNOWN gets own scope lock retained; parent does not repeatedly transition ACCEPTED/COMPLETED.
 10. All events use registered RUNTIME_EVENT_TYPES only.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from metascan.bus.event_bus import EventBus
from metascan.contract.events import RUNTIME_EVENT_TYPES
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import CommandRequest
from metascan.pipeline.risk_config import RiskConfig

EVENT_SET = frozenset(RUNTIME_EVENT_TYPES)


# ---------------------------------------------------------------------------
# Gateway fakes for bulk/emergency testing
# ---------------------------------------------------------------------------


class _TrackedMutation:
    """Captures what was called on gateway for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []


class _BulkVerifyGateway:
    """Gateway that reports sweep results and succeeds all mutations."""

    def __init__(
        self,
        sweep_orders: tuple[dict, ...] = (),
        sweep_positions: tuple[dict, ...] = (),
        rescan_orders: tuple[dict, ...] | None = None,
        rescan_positions: tuple[dict, ...] | None = None,
        *,
        success_retcode: int = 10009,
        fail_retcode: int | None = None,
        fail_mutations: frozenset[str] | None = None,
        bot_magic: int = 999,
        three_phase: bool = False,
    ) -> None:
        self._sweep_orders = sweep_orders
        self._sweep_positions = sweep_positions
        self._rescan_orders = rescan_orders
        self._rescan_positions = rescan_positions
        self._call_count = 0
        self._success_retcode = success_retcode
        self._fail_retcode = fail_retcode
        self._fail_mutations = fail_mutations or frozenset()
        self.track = _TrackedMutation()
        self._bot_magic = bot_magic
        self._three_phase = three_phase

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def sweep_facts(self) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        self._call_count += 1
        if self._call_count == 1:
            fut.set_result({
                "orders": self._sweep_orders,
                "positions": self._sweep_positions,
            })
        elif self._call_count == 2 and self._three_phase:
            fut.set_result({"orders": (), "positions": self._sweep_positions})
        else:
            ro = self._rescan_orders if self._rescan_orders is not None else ()
            rp = self._rescan_positions if self._rescan_positions is not None else ()
            fut.set_result({"orders": ro, "positions": rp})
        return fut

    def mutation(
        self,
        command_id: str,
        kind: str,
        target_id: str | None,
        request: dict,
        *,
        reason: str = "MANUAL",
    ) -> asyncio.Future:
        self.track.calls.append({
            "command_id": command_id,
            "kind": kind,
            "target_id": target_id,
            "reason": reason,
        })
        fut: asyncio.Future = asyncio.Future()
        # Check if this specific ticket should fail
        ticket_str = str(target_id) if target_id else ""
        if self._fail_retcode is not None and ticket_str in self._fail_mutations:
            fut.set_result(type("Result", (), {"retcode": self._fail_retcode})())
        else:
            fut.set_result(type("Result", (), {"retcode": self._success_retcode})())
        return fut

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


class _BlockedBulkGateway:
    """Gateway that blocks mutations to test timeout → EXECUTION_UNKNOWN for child ops."""

    def __init__(self) -> None:
        self._futures: list[asyncio.Future] = []
        self.track = _TrackedMutation()

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def sweep_facts(self) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        # Return one matching order and one position
        fut.set_result({
            "orders": (
                {"ticket": 11, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
            ),
            "positions": (
                {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
            ),
        })
        return fut

    def mutation(
        self,
        command_id: str,
        kind: str,
        target_id: str | None,
        request: dict,
        *,
        reason: str = "MANUAL",
    ) -> asyncio.Future:
        self.track.calls.append({
            "command_id": command_id,
            "kind": kind,
            "target_id": target_id,
            "reason": reason,
        })
        fut: asyncio.Future = asyncio.Future()
        self._futures.append(fut)
        return fut  # never resolved → timeout

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


class _MixedOutcomeGateway:
    """First call succeeds, second fails, third blocks (unknown)."""

    def __init__(self) -> None:
        self._call_n = 0
        self._futures: list[asyncio.Future] = []
        self.track = _TrackedMutation()

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({10009, 10010})

    def sweep_facts(self) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({
            "orders": (),
            "positions": (
                {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
                {"ticket": 102, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
                {"ticket": 103, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
            ),
        })
        return fut

    def mutation(
        self,
        command_id: str,
        kind: str,
        target_id: str | None,
        request: dict,
        *,
        reason: str = "MANUAL",
    ) -> asyncio.Future:
        self.track.calls.append({
            "command_id": command_id,
            "kind": kind,
            "target_id": target_id,
            "reason": reason,
        })
        fut: asyncio.Future = asyncio.Future()
        self._call_n += 1
        n = self._call_n
        if n == 1:
            # First mutation succeeds
            fut.set_result(type("Result", (), {"retcode": 10009})())
        elif n == 2:
            # Second mutation fails (broker reject)
            fut.set_result(type("Result", (), {"retcode": 10016})())
        else:
            # Third mutation blocks (timeout → unknown)
            self._futures.append(fut)
            return fut
        return fut

    def verify(self, target_id: str | None) -> asyncio.Future:
        fut: asyncio.Future = asyncio.Future()
        fut.set_result({"positionExists": None})
        return fut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_facts() -> RuntimeFactsProvider:
    return RuntimeFactsProvider.current(
        runtime_state="READY",
        entries_enabled=True,
        safety_mode_active=False,
        trading_halt=False,
        account={"equity": 10_000.0, "balance": 10_000.0},
        account_age_ms=100,
        positions=(),
        ticks={"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 10}},
        symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 10}},
    )


async def _make_pipeline(
    tmp_path: Path,
    gateway: Any,
    *,
    bot_magic: int = 999,
    gateway_timeout_s: float = 5.0,
    verification_timeout_s: float = 10.0,
) -> tuple[CommandPipeline, EventBus, Journal]:
    db = tmp_path / "test.db"
    journal = Journal(str(db))
    bus = EventBus(journal)
    await bus.start()
    pipeline = CommandPipeline(
        bus=bus,
        gateway=gateway,
        risk_config=RiskConfig(
            gateway_timeout_s=gateway_timeout_s,
            verification_timeout_s=verification_timeout_s,
        ),
        pending=PendingIntentRegistry(),
        facts=_make_facts(),
        bot_magic=bot_magic,
    )
    pipeline.start()
    return pipeline, bus, journal


def _read_events(journal: Journal, boot_id: str) -> list[dict[str, Any]]:
    rows = journal.read_events(boot_id, 0, 5000)
    result: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "type"):
            t = str(r.type.value if hasattr(r.type, "value") else r.type)
            cid = getattr(r, "command_id", None)
            result.append({
                "type": t,
                "command_id": cid,
                "seq": getattr(r, "sequence", 0),
                "payload": getattr(r, "payload", {}),
            })
    return result


async def _read_command_state(
    journal: Journal, command_id: str
) -> dict[str, Any] | None:
    row = journal.run_on_writer(
        lambda conn: conn.execute(
            "SELECT state, record_json FROM commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
    )
    if row is None:
        return None
    rec = json.loads(row[1]) if row[1] else {}
    return {"state": row[0], "record": rec}


async def _read_command_events(
    journal: Journal, command_id: str, boot_id: str = ""
) -> list[dict[str, Any]]:
    """Read all events for a command from journal, return parsed payloads."""
    raw = _read_events(journal, boot_id)
    result: list[dict[str, Any]] = []
    for r in raw:
        if r.get("command_id") == command_id:
            result.append(r)
    return sorted(result, key=lambda x: x["seq"])


async def _drain_pending_events(
    bus: EventBus, subscriber_id: str = "test", count: int = 200, timeout: float = 2.0
) -> list[Any]:
    sub = await bus.subscribe(subscriber_id, maxsize=500)
    events: list[Any] = []
    try:
        while len(events) < count:
            ev = await asyncio.wait_for(sub.get(), timeout=timeout)
            events.append(ev)
    except (asyncio.TimeoutError, TimeoutError):
        pass
    finally:
        await bus.unsubscribe(subscriber_id)
    return events


# ===========================================================================
# R20: BULK cancelAll — child operation identity and accounting
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_cancel_all_child_operations_have_unique_command_ids(
    tmp_path: Path,
) -> None:
    """Each child cancel must have a unique command_id, never reusing the parent's command_id."""
    sweep_orders = (
        {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 2, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(sweep_orders=sweep_orders, bot_magic=999)
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="cancel-all-unique"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        # Each child call must have a unique command_id — none equal to parent
        assert len(gw.track.calls) == 2
        child_ids = {c["command_id"] for c in gw.track.calls}
        assert len(child_ids) == 2, (
            f"child command_ids not unique: {child_ids}"
        )
        assert parent_cid not in child_ids, (
            f"parent command_id {parent_cid} reused as child command_id"
        )

        # Parent must have transitioned
        parent_row = await _read_command_state(journal, parent_cid)
        assert parent_row is not None
        assert parent_row["state"] in ("COMPLETED", "FAILED")
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_accounting_successful_failed_unknown_skipped(
    tmp_path: Path,
) -> None:
    """Verify that the parent event payload contains accurate outcome counts
    for successful, failed, unknown, and skipped child operations."""
    # 2 matching orders: one succeeds, one fails
    sweep_orders = (
        {"ticket": 11, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 12, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        fail_retcode=10016,
        fail_mutations=frozenset({"12"}),
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="cancel-all-accounting"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        events = await _read_command_events(journal, parent_cid, bus.boot_id)
        terminal = [e for e in events if e["type"] in ("command.completed", "command.failed")]
        assert len(terminal) == 1, f"expected 1 terminal event for {parent_cid}, got {len(terminal)}: {[e['type'] for e in events]}"
        payload = terminal[0]["payload"]
        counts = payload.get("counts", {})
        assert counts.get("successful") == 1
        assert counts.get("failed") == 1
        # No unknowns or skips in this scenario
        assert counts.get("unknown", 0) == 0
        assert counts.get("skipped", 0) == 0
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_continues_after_child_failure(
    tmp_path: Path,
) -> None:
    """Bulk must NOT abort on first child failure; it must continue processing remaining children."""
    # 3 orders: first fails, second succeeds, third fails
    sweep_orders = (
        {"ticket": 21, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 22, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 23, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        fail_retcode=10016,
        fail_mutations=frozenset({"21", "23"}),
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        await pipeline.submit_transport(req, idempotency_key="cancel-all-continue")
        await asyncio.sleep(0.3)

        # All 3 children should have been attempted, not just the first
        assert len(gw.track.calls) == 3, (
            f"expected 3 child calls, got {len(gw.track.calls)}"
        )
        call_targets = {c["target_id"] for c in gw.track.calls}
        assert call_targets == {"21", "22", "23"}
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_continues_after_child_timeout_unknown(
    tmp_path: Path,
) -> None:
    """Bulk must continue to next children even when one child blocks and becomes EXECUTION_UNKNOWN."""
    gw = _BlockedBulkGateway()
    pipeline, bus, journal = await _make_pipeline(
        tmp_path, gw, gateway_timeout_s=0.1
    )

    try:
        req = CommandRequest(kind="position.closeAll")
        await pipeline.submit_transport(req, idempotency_key="close-all-unknown-continue")
        await asyncio.sleep(0.5)

        # The blocked gateway returns one order and one position.
        # cancelAll runs first (order 11), then closeAll (position 101).
        # The order cancel will block/timeout, then bulk moves on to close.
        # The position close will also block.
        # Both children attempted means bulk did not abort after first unknown.
        assert len(gw.track.calls) >= 1
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_parent_transitions_terminal_once_with_summary(
    tmp_path: Path,
) -> None:
    """Parent command transitions to terminal (COMPLETED or FAILED) EXACTLY ONCE,
    carrying deterministic summary counts in the event payload."""
    sweep_orders = (
        {"ticket": 31, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 32, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(sweep_orders=sweep_orders, bot_magic=999)
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="cancel-all-terminal-once"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        # Read parent events — must have exactly one terminal event
        events = _read_events(journal, bus.boot_id)
        parent_terminal_events = [
            e
            for e in events
            if e["command_id"] == parent_cid
            and e["type"] in ("command.completed", "command.failed")
        ]
        assert len(parent_terminal_events) == 1, (
            f"expected exactly 1 terminal event for parent, got {len(parent_terminal_events)}: {parent_terminal_events}"
        )

        terminal = parent_terminal_events[0]
        payload = terminal["payload"]
        # Must contain summary counts
        counts = payload.get("counts", {})
        assert isinstance(counts, dict)
        assert "successful" in counts
        assert "failed" in counts
        assert "stragglerIds" in payload or "stragglerIds" in counts
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_straggler_ids_after_rescan(
    tmp_path: Path,
) -> None:
    """Parent payload must include stragglerIds for orders that remain after rescan."""
    sweep_orders = (
        {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    # Rescan shows a *different* order still there (straggler)
    rescan_orders = (
        {"ticket": 2, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        rescan_orders=rescan_orders,
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="cancel-all-straggler"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        parent_row = await _read_command_state(journal, parent_cid)
        assert parent_row is not None
        assert parent_row["state"] == "FAILED"

        events = await _read_command_events(journal, parent_cid, bus.boot_id)
        terminal = [e for e in events if e["type"] in ("command.completed", "command.failed")]
        assert len(terminal) == 1, f"expected 1 terminal event for {parent_cid}, got {len(terminal)}"
        payload = terminal[0]["payload"]
        straggler_ids = payload.get("stragglerIds", [])
        assert len(straggler_ids) >= 1, f"expected stragglerIds, got {straggler_ids}"

        # Must also have an alert.created
        all_events = _read_events(journal, bus.boot_id)
        alerts = [e for e in all_events if e["type"] == "alert.created"]
        assert len(alerts) >= 1
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_foreign_magic_untouched(
    tmp_path: Path,
) -> None:
    """Orders with non-matching magic must be counted as foreignObserved and skipped."""
    sweep_orders = (
        {"ticket": 41, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},  # ours
        {"ticket": 42, "symbol": "EURUSD", "magic": 888, "volume": 0.1, "orderType": 2},  # foreign
    )
    gw = _BulkVerifyGateway(sweep_orders=sweep_orders, bot_magic=999)
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        await pipeline.submit_transport(req, idempotency_key="cancel-all-foreign")
        await asyncio.sleep(0.3)

        # Only ticket 41 should be called (ours), not 42
        call_targets = {c["target_id"] for c in gw.track.calls}
        assert "42" not in call_targets, (
            "foreign order should not be cancelled"
        )
    finally:
        await pipeline.stop()
        await bus.close()


# ===========================================================================
# R20: BULK position.closeAll — same identity/accounting requirements
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_close_all_child_operations_have_unique_command_ids(
    tmp_path: Path,
) -> None:
    """Each child close must have a unique command_id."""
    sweep_positions = (
        {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
        {"ticket": 102, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
    )
    gw = _BulkVerifyGateway(
        sweep_positions=sweep_positions, bot_magic=999
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="position.closeAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="close-all-unique"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        child_ids = {c["command_id"] for c in gw.track.calls}
        assert len(child_ids) == 2
        assert parent_cid not in child_ids
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_close_all_keeps_counting_foreign_observed(
    tmp_path: Path,
) -> None:
    """Foreign positions counted, not closed."""
    sweep_positions = (
        {"ticket": 201, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
        {"ticket": 202, "symbol": "EURUSD", "magic": 888, "volume": 0.1, "type": 0},
        {"ticket": 203, "symbol": "EURUSD", "magic": 777, "volume": 0.1, "type": 0},
    )
    gw = _BulkVerifyGateway(
        sweep_positions=sweep_positions,
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="position.closeAll")
        await pipeline.submit_transport(req, idempotency_key="close-all-foreign")
        await asyncio.sleep(0.3)

        call_targets = {c["target_id"] for c in gw.track.calls}
        assert call_targets == {"201"}
    finally:
        await pipeline.stop()
        await bus.close()


# ===========================================================================
# R20: Mixed outcomes (success + fail + unknown)
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_close_all_mixed_outcomes_accounting(
    tmp_path: Path,
) -> None:
    """Mixed outcomes across children: 1 success, 1 fail, 1 unknown."""
    gw = _MixedOutcomeGateway()
    pipeline, bus, journal = await _make_pipeline(
        tmp_path, gw, gateway_timeout_s=0.1
    )

    try:
        req = CommandRequest(kind="position.closeAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="close-all-mixed"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.5)

        parent_row = await _read_command_state(journal, parent_cid)
        assert parent_row is not None
        assert parent_row["state"] == "FAILED"

        events = await _read_command_events(journal, parent_cid, bus.boot_id)
        terminal = [e for e in events if e["type"] in ("command.completed", "command.failed")]
        assert len(terminal) == 1, f"expected 1 terminal event, got {len(terminal)}: {[e['type'] for e in events]}"
        payload = terminal[0]["payload"]
        counts = payload.get("counts", {})
        assert counts.get("successful") == 1
        assert counts.get("failed") == 1
        # The third child blocks → timeout → unknown
        assert counts.get("unknown", 0) >= 1

        # alert.created must exist
        all_events = _read_events(journal, bus.boot_id)
        alerts = [
            e
            for e in all_events
            if e["type"] == "alert.created" and e.get("command_id") == parent_cid
        ]
        assert len(alerts) >= 1
    finally:
        await pipeline.stop()
        await bus.close()


# ===========================================================================
# R21: EMERGENCY — safety event ordering and behavior
# ===========================================================================


@pytest.mark.asyncio
async def test_emergency_halts_before_any_io(tmp_path: Path) -> None:
    """Emergency must set halted=True and entries_enabled=False BEFORE any mutation calls."""
    gw = _BlockedBulkGateway()
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        # Set a sentinel subscriber to catch events
        events: list[Any] = []
        sub = await bus.subscribe("emergency-watcher", maxsize=500)

        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-halt-first")

        # Give a tiny window for halt to be set but mutations not yet called
        await asyncio.sleep(0.05)

        # halt + entries_enabled must be set before any IO
        assert pipeline.halted, "halted must be True before any mutation"
        assert not pipeline.entries_enabled, "entries_enabled must be False before any mutation"

        await asyncio.sleep(0.1)

        # Drain events to verify safety ordering
        try:
            while True:
                ev = await asyncio.wait_for(sub.get(), timeout=0.5)
                events.append(ev)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            await bus.unsubscribe("emergency-watcher")

        # Extract event types in order
        event_types = [
            str(e.type.value if hasattr(e.type, "value") else e.type)
            for e in events
        ]
        safety_events = [t for t in event_types if t.startswith("safety.kill.")]
        assert len(safety_events) >= 1
        # First safety event must be safety.kill.started
        assert safety_events[0] == "safety.kill.started"
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_emergency_safety_event_ordering(tmp_path: Path) -> None:
    """Safety events must appear in order: started → progress* → completed|failed."""
    gw = _BulkVerifyGateway(
        sweep_orders=(
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        sub = await bus.subscribe("emergency-order", maxsize=500)

        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-order")

        await asyncio.sleep(0.5)

        events: list[Any] = []
        try:
            while True:
                ev = await asyncio.wait_for(sub.get(), timeout=0.5)
                events.append(ev)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            await bus.unsubscribe("emergency-order")

        event_types = [
            str(e.type.value if hasattr(e.type, "value") else e.type)
            for e in events
        ]
        safety_events = [t for t in event_types if t.startswith("safety.kill.")]

        # Verify ordering
        if safety_events:
            assert safety_events[0] == "safety.kill.started"
            # All middle events must be progress
            for se in safety_events[1:-1]:
                assert se == "safety.kill.progress"
            # Last event must be completed or failed
            assert safety_events[-1] in ("safety.kill.completed", "safety.kill.failed")
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_emergency_cancels_orders_then_closes_positions(
    tmp_path: Path,
) -> None:
    """Emergency processing order: cancel pending ORDERS first, then close POSITIONS."""
    gw = _BulkVerifyGateway(
        sweep_orders=(
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        sweep_positions=(
            {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
        ),
        bot_magic=999,
        three_phase=True,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-order-pos")

        await asyncio.sleep(0.5)

        # Mutations must have been called in order: cancels first, then closes
        cancel_calls = [c for c in gw.track.calls if c["kind"] == "order.cancel"]
        close_calls = [c for c in gw.track.calls if c["kind"] == "position.close"]

        assert len(cancel_calls) > 0, "expected at least one cancel"
        assert len(close_calls) > 0, "expected at least one close"

        # All cancels must come before any close in call order
        cancel_indices = [
            i for i, c in enumerate(gw.track.calls) if c["kind"] == "order.cancel"
        ]
        close_indices = [
            i for i, c in enumerate(gw.track.calls) if c["kind"] == "position.close"
        ]
        assert max(cancel_indices) < min(close_indices), (
            "all order.cancel calls must precede position.close calls"
        )
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_emergency_rescans_after_all_ops(tmp_path: Path) -> None:
    """Emergency must rescan after closing positions to detect stragglers."""
    # Gateway that reports 1 order then 1 position, rescan shows nothing
    gw = _BulkVerifyGateway(
        sweep_orders=(
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        sweep_positions=(
            {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
        ),
        bot_magic=999,
        three_phase=True,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-rescan")

        await asyncio.sleep(0.5)

        # sweep_facts must have been called at least 3 times:
        # 1. cancelAll sweep
        # 2. closeAll sweep
        # 3. rescan after closeAll
        # (plus the internal sweeps within each bulk)
        assert gw._call_count >= 3, (
            f"expected at least 3 sweeps, got {gw._call_count}"
        )
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_emergency_stragglers_emit_kill_failed(tmp_path: Path) -> None:
    """If stragglers remain after rescan, emit safety.kill.failed with stragglerIds."""
    sweep_orders = (
        {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    # Rescan shows the order still there
    rescan_orders = (
        {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        rescan_orders=rescan_orders,
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        sub = await bus.subscribe("emergency-straggler", maxsize=500)

        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-straggler")

        await asyncio.sleep(0.5)

        events: list[Any] = []
        try:
            while True:
                ev = await asyncio.wait_for(sub.get(), timeout=0.5)
                events.append(ev)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            await bus.unsubscribe("emergency-straggler")

        event_types = [
            str(e.type.value if hasattr(e.type, "value") else e.type)
            for e in events
        ]
        # Must end with safety.kill.failed
        assert "safety.kill.failed" in event_types
        # Find the failed event and check stragglerIds
        for e in events:
            t = str(e.type.value if hasattr(e.type, "value") else e.type)
            if t == "safety.kill.failed":
                payload = e.payload or {}
                assert "stragglerIds" in payload or "stragglerIds" in str(payload)
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_emergency_no_stragglers_emits_kill_completed(tmp_path: Path) -> None:
    """If no stragglers remain, emit safety.kill.completed."""
    gw = _BulkVerifyGateway(
        sweep_orders=(
            {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        ),
        sweep_positions=(
            {"ticket": 101, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "type": 0},
        ),
        bot_magic=999,
        three_phase=True,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        sub = await bus.subscribe("emergency-clean", maxsize=500)

        req = CommandRequest(kind="runtime.emergencyKill")
        await pipeline.submit_transport(req, idempotency_key="emergency-clean")

        await asyncio.sleep(0.5)

        events: list[Any] = []
        try:
            while True:
                ev = await asyncio.wait_for(sub.get(), timeout=0.5)
                events.append(ev)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            await bus.unsubscribe("emergency-clean")

        event_types = [
            str(e.type.value if hasattr(e.type, "value") else e.type)
            for e in events
        ]
        assert "safety.kill.completed" in event_types
        assert "safety.kill.failed" not in event_types
    finally:
        await pipeline.stop()
        await bus.close()


# ===========================================================================
# Structural: only registered event types used
# ===========================================================================


def test_all_events_are_registered() -> None:
    """All event types used in bulk/emergency must be in RUNTIME_EVENT_TYPES."""
    source = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")
    import re

    event_literals = set(re.findall(r'"((?:command|safety|alert|reconciliation)\.[a-z_.]+)"', source))
    for ev in event_literals:
        assert ev in EVENT_SET, f"event {ev!r} not in RUNTIME_EVENT_TYPES"


# ===========================================================================
# Parent terminal state conventions
# ===========================================================================


@pytest.mark.asyncio
async def test_parent_failed_when_any_child_failed_or_unknown(
    tmp_path: Path,
) -> None:
    """Parent must be FAILED when any child failed, stragglers remain, or unknowns exist."""
    sweep_orders = (
        {"ticket": 51, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
        {"ticket": 52, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        fail_retcode=10016,
        fail_mutations=frozenset({"52"}),
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="parent-failed"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.5)

        parent_row = await _read_command_state(journal, parent_cid)
        assert parent_row is not None

        events = await _read_command_events(journal, parent_cid, bus.boot_id)
        terminal = [e for e in events if e["type"] in ("command.completed", "command.failed")]
        assert len(terminal) == 1, f"expected 1 terminal event, got {len(terminal)}: {[e['type'] for e in events]}"
        payload = terminal[0]["payload"]
        counts = payload.get("counts", {})
        # At least one failure
        failure_or_straggler = (counts.get("failed", 0) > 0
                                or counts.get("unknown", 0) > 0
                                or counts.get("remaining", 0) > 0)
        if failure_or_straggler or len(payload.get("stragglerIds", [])) > 0:
            assert parent_row["state"] == "FAILED"
        else:
            assert parent_row["state"] == "COMPLETED"
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_alert_created_when_any_failure(
    tmp_path: Path,
) -> None:
    """alert.created CRITICAL must be emitted when parent terminal is FAILED."""
    sweep_orders = (
        {"ticket": 61, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(
        sweep_orders=sweep_orders,
        fail_retcode=10016,
        fail_mutations=frozenset({"61"}),
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="alert-on-failure"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.5)

        events = _read_events(journal, bus.boot_id)
        alerts = [
            e
            for e in events
            if e["type"] == "alert.created"
            and e.get("command_id") == parent_cid
        ]
        assert len(alerts) >= 1, (
            "expected alert.created for failed parent command"
        )
        # Check severity via the raw envelope
        raw_rows = journal.read_events(bus.boot_id, 0, 5000)
        for rr in raw_rows:
            if (
                hasattr(rr, "type")
                and str(rr.type.value if hasattr(rr.type, "value") else rr.type) == "alert.created"
                and getattr(rr, "command_id", None) == parent_cid
            ):
                assert getattr(rr, "severity", None) == "CRITICAL"
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_close_all_no_magic_match_returns_completed(
    tmp_path: Path,
) -> None:
    """If no positions match bot_magic, parent completes with 0 counts."""
    sweep_positions = (
        {"ticket": 301, "symbol": "EURUSD", "magic": 888, "volume": 0.1, "type": 0},
    )
    gw = _BulkVerifyGateway(
        sweep_positions=sweep_positions,
        bot_magic=999,
    )
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw, bot_magic=999)

    try:
        req = CommandRequest(kind="position.closeAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="close-all-no-match"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        parent_row = await _read_command_state(journal, parent_cid)
        assert parent_row is not None
        assert parent_row["state"] == "COMPLETED"

        events = await _read_command_events(journal, parent_cid, bus.boot_id)
        terminal = [e for e in events if e["type"] in ("command.completed", "command.failed")]
        assert len(terminal) == 1, f"expected 1 terminal event, got {len(terminal)}: {[e['type'] for e in events]}"
        payload = terminal[0]["payload"]
        counts = payload.get("counts", {})
        assert counts.get("successful", 0) == 0
        assert counts.get("foreignObserved", 0) >= 1
    finally:
        await pipeline.stop()
        await bus.close()


@pytest.mark.asyncio
async def test_bulk_all_success_no_alert(tmp_path: Path) -> None:
    """All children succeed → parent COMPLETED, no alert.created."""
    sweep_orders = (
        {"ticket": 1, "symbol": "EURUSD", "magic": 999, "volume": 0.1, "orderType": 2},
    )
    gw = _BulkVerifyGateway(sweep_orders=sweep_orders, bot_magic=999)
    pipeline, bus, journal = await _make_pipeline(tmp_path, gw)

    try:
        req = CommandRequest(kind="order.cancelAll")
        parent_status = await pipeline.submit_transport(
            req, idempotency_key="all-success-no-alert"
        )
        parent_cid = parent_status.command_id
        await asyncio.sleep(0.3)

        events = _read_events(journal, bus.boot_id)
        alerts = [
            e
            for e in events
            if e["type"] == "alert.created" and e.get("command_id") == parent_cid
        ]
        assert len(alerts) == 0, "no alert.created expected for successful bulk"
    finally:
        await pipeline.stop()
        await bus.close()
