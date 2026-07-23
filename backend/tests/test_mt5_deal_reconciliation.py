from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import asyncio

import pytest

from helpers import event_type, make_position_row
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import BrokerStateFrame

BOT = 240101


def _frame(positions: list, frame_id: int) -> BrokerStateFrame:
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


async def _consumer(tmp_path, lookup):
    bus = EventBus(Journal(tmp_path / "journal.sqlite"))
    await bus.start()
    return bus, BrokerStateConsumer(
        bus=bus,
        slot=LatestFrameSlot(GatewayMetrics()),
        metrics=GatewayMetrics(),
        bot_magic=BOT,
        runtime_id="rt",
        deal_lookup=lookup,
    )


@pytest.mark.asyncio
async def test_close_reconciles_out_deals_before_emitting_trade_closed(tmp_path) -> None:
    deals = (
        SimpleNamespace(position_id=7, entry=0, volume=0.3, price=2300.0, time_msc=1_720_000_000_000, profit=0.0, commission=-0.4, swap=-0.3, fee=-0.1),
        SimpleNamespace(position_id=7, entry=1, volume=0.1, price=2301.0, time_msc=1_720_000_001_000, profit=5.0, commission=-0.2, swap=-0.1, fee=-0.05),
        SimpleNamespace(position_id=7, entry=1, volume=0.2, price=2303.0, time_msc=1_720_000_003_000, profit=7.0, commission=-0.3, swap=-0.2, fee=-0.05),
    )

    async def lookup(ticket: int):
        assert ticket == 7
        return deals

    bus, consumer = await _consumer(tmp_path, lookup)
    row = make_position_row(ticket=7, magic=BOT, volume=0.3, price_open=2300.0, time_msc=1_720_000_000_000)
    await consumer.process_frame(_frame([row], 1))
    events = await consumer.process_frame(_frame([], 2))
    assert [event_type(event) for event in events] == ["position.closed"]
    await asyncio.sleep(0)
    events = await consumer.process_frame(_frame([], 3))
    trade = next(event for event in events if event_type(event) == "trade.closed")

    assert trade.payload == {
        "tradeId": "t-7", "positionId": "7", "strategyId": "unknown", "symbol": "XAUUSDm", "direction": "LONG",
        "entryPrice": 2300.0, "exitPrice": pytest.approx(2302.3333333333335), "openedAt": "2024-07-03T09:46:40Z",
        "closedAt": "2024-07-03T09:46:43Z", "holdingSeconds": 3, "volumeInitial": 0.3, "grossPnl": 12.0,
        "commission": -1.1, "swap": -0.6, "netPnl": 10.3, "rMultiple": None,
        "mfeR": None, "maeR": None, "exitReason": "MANUAL", "partialFills": [
            {"closedAt": "2024-07-03T09:46:41Z", "price": 2301.0, "volume": 0.1, "netPnl": 4.65},
            {"closedAt": "2024-07-03T09:46:43Z", "price": 2303.0, "volume": 0.2, "netPnl": 6.45},
        ], "tags": ["deal-reconciled"],
    }
    assert "fee" not in trade.payload
    await bus.close()


@pytest.mark.asyncio
async def test_close_returns_while_lookup_is_unresolved(tmp_path) -> None:
    gate = asyncio.Event()

    async def lookup(ticket: int):
        await gate.wait()
        return ()

    bus, consumer = await _consumer(tmp_path, lookup)
    row = make_position_row(ticket=11, magic=BOT)
    await consumer.process_frame(_frame([row], 1))
    events = await asyncio.wait_for(consumer.process_frame(_frame([], 2)), timeout=0.1)
    assert [event_type(event) for event in events] == ["position.closed"]
    gate.set()
    await bus.close()


@pytest.mark.asyncio
async def test_close_without_out_deal_stays_pending_then_emits_issue_once(tmp_path) -> None:
    async def lookup(ticket: int):
        return ()

    bus, consumer = await _consumer(tmp_path, lookup)
    row = make_position_row(ticket=8, magic=BOT)
    await consumer.process_frame(_frame([row], 1))
    events = await consumer.process_frame(_frame([], 2))
    assert [event_type(event) for event in events] == ["position.closed"]

    for frame_id in range(3, 7):
        events = await consumer.process_frame(_frame([], frame_id))
    types = [event_type(event) for event in events]
    assert types == ["reconciliation.issue.detected"]
    issue = events[0]
    assert issue.severity == "WARNING"
    assert issue.payload == {
        "entity": "POSITION", "entityId": "8", "runtimeState": "CLOSED", "brokerState": "DEAL_NOT_FOUND",
        "difference": "Position closed but no broker deal found", "reason": "OUT_DEALS_MISSING",
        "severity": "HIGH", "suggestedAction": "Check MT5 deal history and reconcile the position before further action", "resolved": False,
    }
    assert "trade.closed" not in types
    assert not (await consumer.process_frame(_frame([], 7)))
    await bus.close()


@pytest.mark.asyncio
async def test_stop_emits_issue_for_pending_reconciliation(tmp_path) -> None:
    async def lookup(ticket: int):
        return ()

    bus, consumer = await _consumer(tmp_path, lookup)
    row = make_position_row(ticket=10, magic=BOT)
    await consumer.process_frame(_frame([row], 1))
    await consumer.process_frame(_frame([], 2))
    await consumer.stop()
    types = [event_type(event) for event in bus.journal.read_events(bus.boot_id, 0, 100)]
    assert types.count("reconciliation.issue.detected") == 1
    issue = next(event for event in bus.journal.read_events(bus.boot_id, 0, 100) if event_type(event) == "reconciliation.issue.detected")
    assert issue.payload["entity"] == "POSITION"
    assert issue.payload["entityId"] == "10"
    assert issue.payload["reason"] == "SHUTDOWN"
    assert issue.payload["severity"] == "HIGH"
    assert "trade.closed" not in types
    await bus.close()


@pytest.mark.asyncio
async def test_close_lookup_error_emits_issue_not_trade_closed(tmp_path) -> None:
    async def lookup(ticket: int):
        raise TimeoutError("history unavailable")

    bus, consumer = await _consumer(tmp_path, lookup)
    row = make_position_row(ticket=9, magic=BOT)
    await consumer.process_frame(_frame([row], 1))
    events = await consumer.process_frame(_frame([], 2))
    assert [event_type(event) for event in events] == ["position.closed"]
    await asyncio.sleep(0)
    events = await consumer.process_frame(_frame([], 3))
    assert [event_type(event) for event in events] == ["reconciliation.issue.detected"]
    assert events[0].payload["entity"] == "POSITION"
    assert events[0].payload["reason"] == "LOOKUP_FAILED"
    assert events[0].payload["resolved"] is False
    assert "trade.closed" not in [event_type(event) for event in events]
    await bus.close()
