from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer, _envelope
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import AccountRow, BrokerStateFrame, ConsumerFrameState, DashboardReadState, PositionRow, SymbolMeta, TickRow
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.web.routers.snapshot import _read_snapshot


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
    dashboard = DashboardReadState(
        connection_state="DEGRADED", account=None, positions=(), ticks={}, symbol_meta={},
        bot_magic=240101, tick_age_budget_ms=1000.0, last_frame_id=9,
        last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=12.5,
    )
    consumer._frame_state_slot = [ConsumerFrameState(
        connection_state="DEGRADED", quarantine_tickets=frozenset(), hard_fail_streak=0,
        last_tick_mono={}, last_tick_msc={}, degrade_reasons=frozenset(),
        last_positions={}, dashboard=dashboard,
    )]

    state = consumer.dashboard_state()
    consumer._frame_state_slot[0] = ConsumerFrameState(
        connection_state="DEGRADED", quarantine_tickets=frozenset(), hard_fail_streak=0,
        last_tick_mono={}, last_tick_msc={}, degrade_reasons=frozenset(),
        last_positions={}, dashboard=dashboard.with_frame(
            connection_state="DEGRADED", account=None, ticks={}, symbol_meta={}, last_frame_id=10,
            last_frame_at="2026-07-20T00:00:01Z", poll_latency_ms=12.5, positions=(),
        ),
    )

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
    dashboard = DashboardReadState(
        connection_state="CONNECTED", account=None, positions=(managed, foreign), ticks={},
        symbol_meta={meta.resolved: meta}, bot_magic=240101, tick_age_budget_ms=1000.0,
        last_frame_id=1, last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=None,
    )
    consumer._frame_state_slot = [ConsumerFrameState(
        connection_state="CONNECTED", quarantine_tickets=frozenset({foreign.ticket}), hard_fail_streak=0,
        last_tick_mono={}, last_tick_msc={}, degrade_reasons=frozenset({"ALIEN_POSITION"}),
        last_positions={managed.ticket: managed}, dashboard=dashboard,
    )]

    state = consumer.dashboard_state()

    assert state.positions == (managed, foreign)
    assert state.symbol_meta[meta.resolved] is meta
    assert state.bot_magic == 240101


def _position(*, ticket: int, magic: int) -> PositionRow:
    return PositionRow(ticket, "XAUUSDm", magic, 0.1, 2300.0, 2301.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0, 1_700_000_000_000, ticket, "")


def test_cold_start_and_authoritative_flat_have_distinct_availability() -> None:
    cold = DashboardReadState(
        connection_state="DISCONNECTED", account=None, positions=(), ticks={}, symbol_meta={},
        bot_magic=240101, tick_age_budget_ms=1000.0, last_frame_id=0,
        last_frame_at=None, poll_latency_ms=None, positions_available=False,
    )
    flat = cold.with_frame(
        connection_state="CONNECTED", account=None, ticks={}, symbol_meta={},
        last_frame_id=1, last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=1.0,
        positions=(),
    )

    assert (cold.positions_available, cold.positions_frame_id, cold.positions_observed_at) == (False, 0, None)
    assert (flat.positions_available, flat.positions_frame_id, flat.positions_observed_at) == (True, 1, "2026-07-20T00:00:00Z")


def test_account_availability_retains_provenance_until_recovery() -> None:
    account1 = AccountRow(1, 100.0, 101.0, 1.0, 100.0, 101.0, "USD", 0, 0)
    account2 = AccountRow(1, 200.0, 201.0, 2.0, 199.0, 100.5, "USD", 0, 0)
    cold = DashboardReadState(
        connection_state="DISCONNECTED", account=None, positions=(), ticks={}, symbol_meta={},
        bot_magic=1, tick_age_budget_ms=1000.0, last_frame_id=0, last_frame_at=None,
        poll_latency_ms=None, positions_available=False,
    )
    success = cold.with_frame(connection_state="CONNECTED", account=account1, ticks={}, symbol_meta={}, last_frame_id=1, last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=1.0, positions=())
    failed = success.with_frame(connection_state="DEGRADED", account=None, ticks={}, symbol_meta={}, last_frame_id=2, last_frame_at="2026-07-20T00:00:01Z", poll_latency_ms=1.0, positions=())
    recovered = failed.with_frame(connection_state="CONNECTED", account=account2, ticks={}, symbol_meta={}, last_frame_id=3, last_frame_at="2026-07-20T00:00:02Z", poll_latency_ms=1.0, positions=())

    assert (cold.account_available, cold.account_frame_id, cold.account_observed_at) == (False, None, None)
    assert (success.account, success.account_available, success.account_frame_id) == (account1, True, 1)
    assert (failed.account, failed.account_available, failed.account_frame_id, failed.account_observed_at) == (account1, False, 1, "2026-07-20T00:00:00Z")
    assert (recovered.account, recovered.account_available, recovered.account_frame_id) == (account2, True, 3)


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


@pytest.mark.asyncio
async def test_consumer_batch_never_exposes_new_cursor_with_old_state(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    bus = EventBus(journal)
    await bus.start()
    metrics = GatewayMetrics()
    consumer = BrokerStateConsumer(
        bus=bus,
        slot=LatestFrameSlot(metrics),
        metrics=metrics,
        bot_magic=240101,
        runtime_id="rt",
    )
    subscriber = await bus.subscribe("dashboard-test")
    committed = asyncio.Event()
    release = asyncio.Event()
    original = journal.append_events_committed

    def pause_after_commit(envelopes):
        original(envelopes)
        asyncio.run_coroutine_threadsafe(_signal_and_wait(), loop).result()

    async def _signal_and_wait() -> None:
        committed.set()
        await release.wait()

    loop = asyncio.get_running_loop()
    journal.append_events_committed = pause_after_commit
    frame = BrokerStateFrame(
        frame_id=1, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:00Z", positions=(_position(ticket=1, magic=99),),
        account=None, ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}),
        errors=(), mt5_last_error=None,
    )
    publication = asyncio.create_task(consumer.process_frame(frame))
    await committed.wait()
    capture = asyncio.create_task(bus.capture_boundary(consumer.dashboard_state))
    await asyncio.sleep(0)
    assert capture.done() is False
    release.set()
    published = await publication
    state, _, revision, sequence = await capture
    delivered = await subscriber.get()

    assert state.last_frame_id == 1
    assert revision == sequence == len(published)
    assert delivered.sequence == 1
    await bus.close()


@pytest.mark.asyncio
async def test_batch_cancellation_finishes_commit_state_and_fanout(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "cancel.sqlite")
    bus = EventBus(journal)
    await bus.start()
    subscriber = await bus.subscribe("cancel-test")
    slot = ["old"]
    entered = asyncio.Event()
    release = asyncio.Event()
    original = journal.append_events_committed
    loop = asyncio.get_running_loop()

    def blocked(envelopes):
        loop.call_soon_threadsafe(entered.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        original(envelopes)

    journal.append_events_committed = blocked
    event = _envelope(type_="runtime.health.changed", runtime_id="rt", wall_iso="2026-07-20T00:00:00Z", payload={})
    task = asyncio.create_task(bus.publish_state_batch(slot, "new", (event,)))
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    delivered = await subscriber.get()
    assert slot[0] == "new"
    assert delivered.sequence == bus.sequence == 1
    await bus.close()


@pytest.mark.asyncio
async def test_batch_repeated_cancellation_finishes_commit_state_and_fanout(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "double-cancel.sqlite")
    bus = EventBus(journal)
    await bus.start()
    subscriber = await bus.subscribe("double-cancel-test")
    slot = ["old"]
    entered = asyncio.Event()
    release = asyncio.Event()
    original = journal.append_events_committed
    loop = asyncio.get_running_loop()

    def blocked(envelopes):
        loop.call_soon_threadsafe(entered.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        original(envelopes)

    journal.append_events_committed = blocked
    event = _envelope(type_="runtime.health.changed", runtime_id="rt", wall_iso="2026-07-20T00:00:00Z", payload={})
    task = asyncio.create_task(bus.publish_state_batch(slot, "new", (event,)))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert slot[0] == "old"
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    delivered = await subscriber.get()
    assert slot[0] == "new"
    assert delivered.sequence == bus.sequence == 1
    await bus.close()


@pytest.mark.asyncio
async def test_cancelled_failed_commit_rolls_back_and_propagates_cancellation(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "cancel-failed.sqlite")
    bus = EventBus(journal)
    await bus.start()
    slot = ["old"]
    entered = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocked_failure(envelopes):
        loop.call_soon_threadsafe(entered.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        raise RuntimeError("journal unavailable")

    journal.append_events_committed = blocked_failure
    event = _envelope(type_="runtime.health.changed", runtime_id="rt", wall_iso="2026-07-20T00:00:00Z", payload={})
    task = asyncio.create_task(bus.publish_state_batch(slot, "new", (event,)))
    await entered.wait()
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await task

    assert isinstance(cancelled.value.__cause__, RuntimeError)
    assert slot[0] == "old"
    assert bus.sequence == bus.revision == 0
    await bus.close()


@pytest.mark.asyncio
async def test_cancelled_pending_close_is_finalized_with_committed_state(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "pending-cancel.sqlite")
    bus = EventBus(journal)
    await bus.start()
    metrics = GatewayMetrics()
    pending = PendingIntentRegistry()
    consumer = BrokerStateConsumer(bus=bus, slot=LatestFrameSlot(metrics), metrics=metrics, bot_magic=240101, runtime_id="rt", pending=pending)
    opened = BrokerStateFrame(
        frame_id=1, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:00Z", positions=(_position(ticket=7, magic=240101),), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(opened)
    pending.register_close(7, "cmd-7")
    closed = BrokerStateFrame(
        frame_id=2, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:01Z", positions=(), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    original = journal.append_events_committed
    loop = asyncio.get_running_loop()

    def blocked(envelopes):
        loop.call_soon_threadsafe(entered.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        original(envelopes)

    journal.append_events_committed = blocked
    task = asyncio.create_task(consumer.process_frame(closed))
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert pending.has_pending_close(7) is False
    assert consumer.last_positions == {}
    assert any(event.type == "position.closed" for event in journal.read_events(bus.boot_id, 0, 100))
    await bus.close()


@pytest.mark.asyncio
async def test_unavailable_positions_retain_quarantine(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "quarantine.sqlite")
    bus = EventBus(journal)
    await bus.start()
    metrics = GatewayMetrics()
    consumer = BrokerStateConsumer(bus=bus, slot=LatestFrameSlot(metrics), metrics=metrics, bot_magic=240101, runtime_id="rt")
    foreign = _position(ticket=9, magic=99)
    available = BrokerStateFrame(
        frame_id=1, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:00Z", positions=(foreign,), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    unavailable = BrokerStateFrame(
        frame_id=2, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:01Z", positions=(), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
        positions_unavailable=True,
    )

    await consumer.process_frame(available)
    published = await consumer.process_frame(unavailable)

    assert consumer.quarantine_tickets == frozenset({9})
    assert not any(event.type == "alert.created" for event in published)
    await bus.close()


@pytest.mark.asyncio
async def test_connection_transition_is_reemitted_after_journal_failure(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "connection-retry.sqlite")
    bus = EventBus(journal)
    await bus.start()
    metrics = GatewayMetrics()
    consumer = BrokerStateConsumer(
        bus=bus,
        slot=LatestFrameSlot(metrics),
        metrics=metrics,
        bot_magic=240101,
        runtime_id="rt",
    )
    frame = BrokerStateFrame(
        frame_id=1, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:00Z", positions=(), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    original = journal.append_events_committed
    attempts = 0

    def fail_once(envelopes):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("journal unavailable")
        original(envelopes)

    journal.append_events_committed = fail_once

    failed = await consumer.process_frame(frame)
    assert failed == []
    assert journal.read_events(bus.boot_id, 0, 100) == []
    assert consumer.connection_state == "DISCONNECTED"
    assert consumer.dashboard_state().last_frame_id == 0

    published = await consumer.process_frame(frame)

    assert [event.type for event in published] == ["broker.connection.changed", "runtime.health.changed"]
    assert consumer.connection_state == "CONNECTED"
    assert consumer.dashboard_state().last_frame_id == 1
    await bus.close()


@pytest.mark.asyncio
async def test_position_lifecycle_is_reemitted_after_journal_failure(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "position-retry.sqlite")
    bus = EventBus(journal)
    await bus.start()
    metrics = GatewayMetrics()
    consumer = BrokerStateConsumer(
        bus=bus,
        slot=LatestFrameSlot(metrics),
        metrics=metrics,
        bot_magic=240101,
        runtime_id="rt",
    )
    empty = BrokerStateFrame(
        frame_id=1, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:00Z", positions=(), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    await consumer.process_frame(empty)
    opened = BrokerStateFrame(
        frame_id=2, cycle_started_m=0.0, cycle_finished_m=0.01, cycle_duration_ms=10.0,
        polled_at_wall="2026-07-20T00:00:01Z", positions=(_position(ticket=7, magic=240101),), account=None,
        ticks=MappingProxyType({}), symbol_meta=MappingProxyType({}), errors=(), mt5_last_error=None,
    )
    original = journal.append_events_committed
    attempts = 0

    def fail_once(envelopes):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("journal unavailable")
        original(envelopes)

    journal.append_events_committed = fail_once

    failed = await consumer.process_frame(opened)
    assert failed == []
    assert not any(event.type == "position.opened" for event in journal.read_events(bus.boot_id, 0, 100))
    assert consumer.last_positions == {}
    assert consumer.dashboard_state().last_frame_id == 1

    published = await consumer.process_frame(opened)

    assert [event.type for event in published] == ["position.opened"]
    assert consumer.last_positions == {7: opened.positions[0]}
    assert consumer.dashboard_state().last_frame_id == 2
    await bus.close()


def test_snapshot_account_four_state_uses_account_provenance() -> None:
    import datetime

    account1 = AccountRow(1, 100.0, 101.0, 1.0, 100.0, 101.0, "USD", 0, 0)
    account2 = AccountRow(1, 200.0, 201.0, 2.0, 199.0, 100.5, "USD", 0, 0)
    position = _position(ticket=1, magic=240101)
    now = datetime.datetime(2026, 7, 20, 0, 0, 10, tzinfo=datetime.timezone.utc)
    cold = DashboardReadState(
        connection_state="DISCONNECTED", account=None, positions=(), ticks={}, symbol_meta={},
        bot_magic=240101, tick_age_budget_ms=1000.0, last_frame_id=0, last_frame_at=None,
        poll_latency_ms=None, positions_available=False,
    )
    success = cold.with_frame(connection_state="CONNECTED", account=account1, ticks={}, symbol_meta={}, last_frame_id=1, last_frame_at="2026-07-20T00:00:00Z", poll_latency_ms=1.0, positions=(position,))
    failed = success.with_frame(connection_state="DEGRADED", account=None, ticks={}, symbol_meta={}, last_frame_id=2, last_frame_at="2026-07-20T00:00:01Z", poll_latency_ms=1.0, positions=())
    recovered = failed.with_frame(connection_state="CONNECTED", account=account2, ticks={}, symbol_meta={}, last_frame_id=3, last_frame_at="2026-07-20T00:00:02Z", poll_latency_ms=1.0, positions=())

    snapshots = [_read_snapshot(state, now_utc=now) for state in (cold, success, failed, recovered)]

    assert [snapshot["account"]["updatedAt"] for snapshot in snapshots] == [
        None,
        "2026-07-20T00:00:00Z",
        "2026-07-20T00:00:00Z",
        "2026-07-20T00:00:02Z",
    ]
    assert [snapshot["accountObservedAt"] for snapshot in snapshots] == [
        None,
        "2026-07-20T00:00:00Z",
        "2026-07-20T00:00:00Z",
        "2026-07-20T00:00:02Z",
    ]
    assert snapshots[2]["account"]["floatingPnl"] is None
    assert snapshots[2]["account"]["openPositions"] is None

    from metascan.contract.models import AccountSnapshot

    validated = AccountSnapshot.model_validate(snapshots[0]["account"])
    assert validated.updated_at is None


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
