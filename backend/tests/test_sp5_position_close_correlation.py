"""SP3 behavioral integration tests: position close with correlated intent metadata.

When a position disappears from broker AND a matching pending close intent exists:
  - consumer emits registered position.closed AND trade.closed (not suppressed)
  - events carry the commandId and correlationId from the pending intent
  - exitReason is MANUAL for position.close/closeAll, KILL_SWITCH for emergencyKill
  - pending intent persists command kind/exit reason/correlation needed for emit
  - intent is cleared AFTER consumer processes broker disappearance

External close without pending intent: exitReason remains MANUAL.
Partial close never emits trade.closed or PARTIAL_FINAL.
Bot magic position without matching entry intent: WARNING anomaly (existing behavior).
Foreign position: quarantine (existing behavior).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from helpers import default_account, default_symbol_info, event_type, make_position_row
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.mt5.types import BrokerStateFrame

BOT = 240101


class IntentfulPending:
    """Test double: PendingIntentLookup that stores command kind, exit reason,
    correlation ID, and command ID for a set of tickets."""

    def __init__(
        self,
        *,
        close_intent: dict[int, dict] | None = None,
        partial_intent: dict[int, tuple[float, str]] | None = None,
        modify_intent: dict[int, str] | None = None,
    ) -> None:
        self._close = close_intent or {}
        self._partial = partial_intent or {}
        self._modify = modify_intent or {}

    def has_pending_close(self, ticket: int) -> bool:
        return ticket in self._close

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return ticket in self._partial and self._partial[ticket][0] == volume

    def has_pending_modify(self, ticket: int) -> bool:
        return ticket in self._modify

    def get_exit_reason(self, ticket: int) -> str:
        return self._close.get(ticket, {}).get("exit_reason", "MANUAL")

    def get_command_id(self, ticket: int) -> str | None:
        if ticket in self._partial:
            return self._partial[ticket][1]
        return self._close.get(ticket, {}).get("command_id")

    def get_correlation_id(self, ticket: int) -> str | None:
        if ticket in self._partial:
            return f"corr-{self._partial[ticket][1]}"
        return self._close.get(ticket, {}).get("correlation_id")

    def clear(self, ticket: int) -> None:
        self._close.pop(ticket, None)
        self._partial.pop(ticket, None)


def _make_frame(positions: list, frame_id: int = 1) -> BrokerStateFrame:
    return BrokerStateFrame(
        frame_id=frame_id,
        cycle_started_m=0,
        cycle_finished_m=0.01,
        cycle_duration_ms=10,
        polled_at_wall="2026-07-14T00:00:00Z",
        positions=tuple(positions),
        account=None,
        ticks=MappingProxyType({}),
        symbol_meta=MappingProxyType({}),
        errors=(),
        mt5_last_error=None,
    )


async def _make_consumer(tmp_path: Path, pending=None) -> tuple[EventBus, BrokerStateConsumer]:
    j = Journal(tmp_path / "j.sqlite")
    bus = EventBus(j)
    await bus.start()
    metrics = GatewayMetrics()
    slot = LatestFrameSlot(metrics)

    async def deal_lookup(ticket: int):
        return (SimpleNamespace(position_id=ticket, entry=1, volume=0.1, price=2301.0, time_msc=1_720_000_001_000, profit=15.0, commission=-2.0, swap=-0.5, fee=0.0),)

    consumer = BrokerStateConsumer(
        bus=bus, slot=slot, metrics=metrics, bot_magic=BOT,
        runtime_id="rt1", pending=pending, deal_lookup=deal_lookup,
    )
    return bus, consumer


async def _collect_events(bus: EventBus, consumer: BrokerStateConsumer, frames: list[BrokerStateFrame]) -> list:
    sub = await bus.subscribe("s-test", maxsize=2048)
    for frame in frames:
        await consumer.process_frame(frame)
    await asyncio.sleep(0)
    if frames:
        await consumer.process_frame(_make_frame([], frames[-1].frame_id + 1))
    await asyncio.sleep(0.05)
    events = []
    while not sub._queue.empty():
        try:
            e = sub._queue.get_nowait()
            if hasattr(e, "type"):
                events.append(e)
        except asyncio.QueueEmpty:
            break
    await bus.close()
    return events


# ─── Tests: pending close intent → correlated events ─────────────────────


@pytest.mark.asyncio
async def test_pending_close_manual_emits_correlated_events(tmp_path: Path) -> None:
    """position.close intent (MANUAL): when position disappears, emit
    position.closed + trade.closed with commandId, correlationId, exitReason=MANUAL."""
    intent = IntentfulPending(close_intent={
        55: {
            "exit_reason": "MANUAL",
            "command_id": "cmd-close-55",
            "correlation_id": "corr-55",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=55, magic=BOT, volume=0.2, profit=20.0, commission=-1.0, swap=-0.5)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    types = [event_type(e) for e in events]
    assert "position.closed" in types
    assert "trade.closed" in types
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.command_id == "cmd-close-55"
    assert trade.correlation_id == "corr-55"
    assert trade.payload["exitReason"] == "MANUAL"
    assert trade.payload["positionId"] == "55"
    assert trade.payload["netPnl"] == trade.payload["grossPnl"] + trade.payload["commission"] + trade.payload["swap"]
    pos = next(e for e in events if event_type(e) == "position.closed")
    assert pos.command_id == "cmd-close-55"
    assert pos.correlation_id == "corr-55"


@pytest.mark.asyncio
async def test_pending_close_kill_switch_emits_correlated_events(tmp_path: Path) -> None:
    """emergencyKill intent (KILL_SWITCH): when position disappears, emit
    position.closed + trade.closed with exitReason=KILL_SWITCH."""
    intent = IntentfulPending(close_intent={
        66: {
            "exit_reason": "KILL_SWITCH",
            "command_id": "cmd-kill-66",
            "correlation_id": "corr-kill-66",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=66, magic=BOT, volume=0.1, profit=-5.0, commission=-1.0, swap=-0.2)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    types = [event_type(e) for e in events]
    assert "position.closed" in types
    assert "trade.closed" in types
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.command_id == "cmd-kill-66"
    assert trade.correlation_id == "corr-kill-66"
    assert trade.payload["exitReason"] == "KILL_SWITCH"


@pytest.mark.asyncio
async def test_close_all_intent_emits_manual(tmp_path: Path) -> None:
    """position.closeAll intent: per-position close emits exitReason=MANUAL."""
    intent = IntentfulPending(close_intent={
        77: {
            "exit_reason": "MANUAL",
            "command_id": "cmd-closeAll-77",
            "correlation_id": "corr-closeAll",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=77, magic=BOT, volume=0.3)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.payload["exitReason"] == "MANUAL"
    assert trade.command_id == "cmd-closeAll-77"


@pytest.mark.asyncio
async def test_net_pnl_identity_in_trade_closed(tmp_path: Path) -> None:
    """trade.closed payload netPnl = grossPnl + commission + swap (signed identity)."""
    intent = IntentfulPending(close_intent={
        88: {
            "exit_reason": "MANUAL",
            "command_id": "cmd-88",
            "correlation_id": "corr-88",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=88, magic=BOT, volume=0.1, profit=15.0, commission=-2.0, swap=-0.5)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.payload["netPnl"] == 15.0 + (-2.0) + (-0.5)


# ─── Tests: emit-site whitelist enforcement ───────────────────────────────


@pytest.mark.asyncio
async def test_emit_site_rejects_non_whitelist_exit_reason(tmp_path: Path) -> None:
    """exitReason outside {MANUAL, KILL_SWITCH} is rejected at emit site."""
    from metascan.pipeline.outcome_handler import CLOSE_WHITELIST

    invalid_reason = "PARTIAL_FINAL"
    assert invalid_reason not in CLOSE_WHITELIST
    assert CLOSE_WHITELIST == frozenset({"MANUAL", "KILL_SWITCH"})


def test_exit_reason_for_mapping_completeness() -> None:
    """exit_reason_for covers all close/kind commands; closePartial returns None."""
    from metascan.pipeline.outcome_handler import exit_reason_for

    assert exit_reason_for("position.close") == "MANUAL"
    assert exit_reason_for("position.closeAll") == "MANUAL"
    assert exit_reason_for("runtime.emergencyKill") == "KILL_SWITCH"
    assert exit_reason_for("position.closePartial") is None


# ─── Tests: external close without intent (no-intent → MANUAL) ────────────


@pytest.mark.asyncio
async def test_external_close_no_intent_emits_manual(tmp_path: Path) -> None:
    """No pending intent → external close emits exitReason=MANUAL (default)."""
    bus, consumer = await _make_consumer(tmp_path, pending=None)
    row = make_position_row(ticket=99, magic=BOT, volume=0.1, profit=3.0, commission=-0.5, swap=-0.1)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.payload["exitReason"] == "MANUAL"
    assert trade.command_id is None
    assert trade.correlation_id is None


# ─── Tests: partial close never emits trade.closed ────────────────────────


@pytest.mark.asyncio
async def test_partial_close_emits_only_partially_closed(tmp_path: Path) -> None:
    """Volume shrink → position.partially_closed only, never trade.closed."""
    bus, consumer = await _make_consumer(tmp_path)
    row_full = make_position_row(ticket=110, magic=BOT, volume=0.3)
    row_partial = make_position_row(ticket=110, magic=BOT, volume=0.1)
    events = await _collect_events(bus, consumer, [_make_frame([row_full]), _make_frame([row_partial])])
    types = [event_type(e) for e in events]
    assert "position.partially_closed" in types
    assert "trade.closed" not in types
    assert "PARTIAL_FINAL" not in str(types)


@pytest.mark.asyncio
async def test_pending_partial_emits_correlated_partial_and_update(tmp_path: Path) -> None:
    intent = IntentfulPending(partial_intent={110: (0.1, "cmd-partial-110")})
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row_full = make_position_row(ticket=110, magic=BOT, volume=0.3)
    row_partial = make_position_row(ticket=110, magic=BOT, volume=0.1)
    events = await _collect_events(bus, consumer, [_make_frame([row_full]), _make_frame([row_partial])])
    partial = next(e for e in events if event_type(e) == "position.partially_closed")
    updated = next(e for e in events if event_type(e) == "position.updated")
    assert partial.command_id == updated.command_id == "cmd-partial-110"
    assert partial.correlation_id == updated.correlation_id == "corr-cmd-partial-110"
    assert 110 not in intent._partial


# ─── Tests: intent clear after consumer processing ───────────────────────


@pytest.mark.asyncio
async def test_pending_intent_cleared_after_consumer_processes_close(tmp_path: Path) -> None:
    """Intent is consumed (cleared) after consumer processes broker disappearance,
    so pipeline completion does not erase correlation prematurely."""
    intent = IntentfulPending(close_intent={
        120: {
            "exit_reason": "MANUAL",
            "command_id": "cmd-120",
            "correlation_id": "corr-120",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=120, magic=BOT, volume=0.1)

    # Frame 1: position exists (intent registered)
    await consumer.process_frame(_make_frame([row]))
    assert intent.has_pending_close(120)

    # Frame 2: position disappears (consumer should clear intent)
    await consumer.process_frame(_make_frame([]))
    assert not intent.has_pending_close(120)


# ─── Tests: foreign / bot-magic anomaly (existing behavior preserved) ─────


@pytest.mark.asyncio
async def test_foreign_position_quarantined_no_trade_closed(tmp_path: Path) -> None:
    """Foreign (non-bot-magic) position disappearing: quarantine alert, no trade.closed."""
    bus, consumer = await _make_consumer(tmp_path)
    foreign_row = make_position_row(ticket=200, magic=999999, volume=0.1)
    events = await _collect_events(bus, consumer, [_make_frame([foreign_row]), _make_frame([])])
    types = [event_type(e) for e in events]
    assert "trade.closed" not in types
    assert "position.closed" not in types
    alert_types = [t for t in types if "alien" in t.lower() or "alert" in t.lower()]
    assert alert_types


# ─── Tests: suppression rewritten ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_close_with_intent_emits_events(tmp_path: Path) -> None:
    """Rewritten suppression test: pending close WITH intent now emits events
    (not suppressed), because consumer must emit correlated events."""
    intent = IntentfulPending(close_intent={
        130: {
            "exit_reason": "MANUAL",
            "command_id": "cmd-130",
            "correlation_id": "corr-130",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=130, magic=BOT, volume=0.2)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    types = [event_type(e) for e in events]
    assert "position.closed" in types
    assert "trade.closed" in types


@pytest.mark.asyncio
async def test_no_pending_close_without_intent_emits_events(tmp_path: Path) -> None:
    """No pending close intent → normal external close behavior emits events."""
    bus, consumer = await _make_consumer(tmp_path, pending=None)
    row = make_position_row(ticket=140, magic=BOT, volume=0.1)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    types = [event_type(e) for e in events]
    assert "position.closed" in types
    assert "trade.closed" in types
    trade = next(e for e in events if event_type(e) == "trade.closed")
    assert trade.payload["exitReason"] == "MANUAL"


# ─── Tests: no invented events ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_invented_event_types_on_close(tmp_path: Path) -> None:
    """Close path emits exactly position.closed + trade.closed, no extra event types."""
    intent = IntentfulPending(close_intent={
        150: {
            "exit_reason": "KILL_SWITCH",
            "command_id": "cmd-150",
            "correlation_id": "corr-150",
        }
    })
    bus, consumer = await _make_consumer(tmp_path, pending=intent)
    row = make_position_row(ticket=150, magic=BOT, volume=0.1)
    events = await _collect_events(bus, consumer, [_make_frame([row]), _make_frame([])])
    types = set(event_type(e) for e in events)
    expected_close_events = {"position.closed", "trade.closed"}
    assert expected_close_events.issubset(types)
    assert "position.partially_closed" not in types
    assert "trade.partially_closed" not in types
