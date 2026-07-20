from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import AccountRow, DashboardReadState, PositionRow, SymbolMeta, TickRow


def test_dashboard_read_state_is_frozen_and_copies_collections() -> None:
    position = PositionRow(
        ticket=7,
        symbol="XAUUSDm",
        magic=240101,
        volume=0.1,
        price_open=2300.0,
        price_current=2301.0,
        sl=2290.0,
        tp=2320.0,
        profit=10.0,
        swap=0.0,
        commission=-0.2,
        type=0,
        time_msc=1_700_000_000_000,
        identifier=8,
        comment="",
    )
    account = AccountRow(1, 1000.0, 1010.0, 100.0, 910.0, 1010.0, "USD", 0, 2)
    tick = TickRow("XAUUSDm", 2300.5, 2301.0, 2300.75, 1_700_000_000_100, 3.0)
    source_ticks = {tick.symbol: tick}

    state = DashboardReadState(
        connection_state="CONNECTED",
        account=account,
        positions=(position,),
        ticks=source_ticks,
        symbol_meta={},
        bot_magic=240101,
        tick_age_budget_ms=1000.0,
        last_frame_id=4,
        last_frame_at="2026-07-20T00:00:00Z",
        poll_latency_ms=12.5,
    )
    source_ticks.clear()

    assert state.ticks == MappingProxyType({tick.symbol: tick})
    assert state.positions == (position,)
    with pytest.raises(FrozenInstanceError):
        state.last_frame_id = 5
    with pytest.raises(TypeError):
        state.ticks[tick.symbol] = tick


def test_consumer_dashboard_state_copies_retained_read_model() -> None:
    metrics = GatewayMetrics()
    metrics.record_cycle_ms(12.5)
    consumer = object.__new__(BrokerStateConsumer)
    consumer._metrics = metrics
    consumer.connection_state = "DEGRADED"
    consumer.last_account = None
    consumer.last_positions = {}
    consumer.dashboard_positions = ()
    consumer.last_ticks = {}
    consumer.last_symbol_meta = {}
    consumer._bot_magic = 240101
    consumer._tick_age_budget_ms = 1000.0
    consumer.last_frame_id = 9
    consumer.last_frame_at = "2026-07-20T00:00:00Z"
    consumer._dashboard_state = DashboardReadState(
        connection_state="DEGRADED", account=None, positions=(), ticks={}, symbol_meta={},
        bot_magic=240101, tick_age_budget_ms=1000.0, last_frame_id=9,
        last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=12.5,
    )

    state = consumer.dashboard_state()
    consumer.last_frame_id = 10

    assert state.connection_state == "DEGRADED"
    assert state.last_frame_id == 9
    assert state.last_frame_at == "2026-07-20T00:00:00Z"
    assert state.poll_latency_ms == 12.5


def test_consumer_dashboard_state_retains_all_positions_and_symbol_metadata() -> None:
    managed = _position(ticket=1, magic=240101)
    foreign = _position(ticket=2, magic=99)
    meta = SymbolMeta("XAUUSD", "XAUUSDm", 2, 0.01, 100.0, 0.01, 1.0, 0.01, 10.0, 0.01, 0, 0, 3, 4, True)
    consumer = object.__new__(BrokerStateConsumer)
    consumer._metrics = GatewayMetrics()
    consumer._bot_magic = 240101
    consumer._tick_age_budget_ms = 1000.0
    consumer.connection_state = "CONNECTED"
    consumer.last_account = None
    consumer.last_positions = {managed.ticket: managed}
    consumer.dashboard_positions = (managed, foreign)
    consumer.last_ticks = {}
    consumer.last_symbol_meta = {meta.resolved: meta}
    consumer.last_frame_id = 1
    consumer.last_frame_at = "2026-07-20T00:00:00Z"
    consumer._dashboard_state = DashboardReadState(
        connection_state="CONNECTED", account=None, positions=(managed, foreign), ticks={},
        symbol_meta={meta.resolved: meta}, bot_magic=240101, tick_age_budget_ms=1000.0,
        last_frame_id=1, last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=None,
    )

    state = consumer.dashboard_state()

    assert state.positions == (managed, foreign)
    assert state.symbol_meta[meta.resolved] is meta
    assert state.bot_magic == 240101


def _position(*, ticket: int, magic: int) -> PositionRow:
    return PositionRow(ticket, "XAUUSDm", magic, 0.1, 2300.0, 2301.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0, 1_700_000_000_000, ticket, "")


def test_unavailable_positions_keep_original_provenance() -> None:
    position = _position(ticket=1, magic=240101)
    previous = DashboardReadState(
        connection_state="CONNECTED", account=None, positions=(position,), ticks={}, symbol_meta={},
        bot_magic=240101, tick_age_budget_ms=1000.0, last_frame_id=1,
        last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=1.0,
        positions_available=True, positions_frame_id=1,
        positions_observed_at="2026-07-20T00:00:00Z",
    )
    current = previous.with_frame(
        connection_state="DEGRADED", account=None, ticks={}, symbol_meta={},
        last_frame_id=2, last_frame_at="2026-07-20T00:00:01Z", poll_latency_ms=2.0,
        positions=None,
    )

    assert current.positions == (position,)
    assert current.positions_available is False
    assert current.positions_frame_id == 1
    assert current.positions_observed_at == "2026-07-20T00:00:00Z"
    assert current.last_frame_id == 2


def test_dashboard_read_state_rejects_invalid_connection_state() -> None:
    with pytest.raises(ValueError, match="invalid dashboard connection state"):
        DashboardReadState(
            connection_state="UNKNOWN",
            account=None,
            positions=(),
            ticks={},
            symbol_meta={},
            bot_magic=None,
            tick_age_budget_ms=1000.0,
            last_frame_id=0,
            last_frame_at=None,
            poll_latency_ms=None,
        )
