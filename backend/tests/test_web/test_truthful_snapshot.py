from __future__ import annotations

import datetime
import pytest

from metascan.mt5.mapping import position_payload
from metascan.mt5.types import DashboardReadState, PositionRow
from metascan.web.routers.snapshot import _empty_snapshot, _read_snapshot


def test_empty_snapshot_lastRunAt_is_null():
    snap = _empty_snapshot()
    assert snap["reconciliation"]["lastRunAt"] is None, (
        "empty snapshot must not contain a fabricated lastRunAt timestamp"
    )


def test_empty_snapshot_account_unavailable_fields_are_null():
    snap = _empty_snapshot()
    acc = snap["account"]
    for field in (
        "balance", "equity", "margin", "freeMargin", "marginLevel",
        "winRate", "profitFactor", "tradesToday", "dailyDrawdown", "maxDrawdown",
        "grossExposure", "netExposure", "pendingOrders", "realizedPnlToday",
        "realizedPnlWeek", "riskUtilization",
    ):
        assert acc[field] is None, (
            f"empty snapshot account.{field} must be null, got {acc[field]!r}"
        )


def test_empty_snapshot_runtime_timestamps_are_null():
    snap = _empty_snapshot()
    rt = snap["runtime"]
    for field in ("startedAt", "stateChangedAt", "lastHeartbeatAt"):
        assert rt[field] is None, (
            f"empty snapshot runtime.{field} must be null, got {rt[field]!r}"
        )


def test_empty_snapshot_runtime_host_fields_are_null():
    snap = _empty_snapshot()
    rt = snap["runtime"]
    assert rt["hostname"] is None
    assert rt["os"] is None
    assert rt["pid"] is None


def test_empty_snapshot_broker_lastRequestAt_is_null():
    snap = _empty_snapshot()
    assert snap["broker"]["lastRequestAt"] is None, (
        "empty snapshot broker.lastRequestAt must be null when no real request has occurred"
    )


def test_read_snapshot_cold_state_has_no_fake_timestamps_or_metrics():
    """When consumer is attached but no MT5 frame has arrived (last_frame_at=None),
    observedAt, lastHeartbeatAt, lastRequestAt must be null (no fallback to now),
    and latency/account metrics must remain null."""
    cold = DashboardReadState(
        connection_state="DISCONNECTED",
        account=None,
        positions=(),
        ticks={},
        symbol_meta={},
        bot_magic=999,
        tick_age_budget_ms=1000.0,
        last_frame_id=0,
        last_frame_at=None,
        poll_latency_ms=None,
        positions_available=False,
        account_available=False,
    )
    now_utc = datetime.datetime(2026, 7, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    snap = _read_snapshot(cold, now_utc=now_utc)

    assert snap["positionsObservedAt"] is None
    assert snap["accountObservedAt"] is None
    assert snap["runtime"]["lastHeartbeatAt"] is None
    assert snap["runtime"]["heartbeatLatencyMs"] is None
    assert snap["broker"]["lastRequestAt"] is None
    assert snap["broker"]["avgLatencyMs"] is None

    acc = snap["account"]
    assert acc["balance"] is None
    assert acc["equity"] is None
    assert acc["winRate"] is None
    assert acc["profitFactor"] is None


def test_position_mapping_uncomputed_metrics_are_null():
    """Open position mapping must not project 0.0 for uncomputed metrics."""
    row = PositionRow(
        ticket=12345,
        symbol="EURUSD",
        magic=999,
        volume=0.1,
        price_open=1.0500,
        price_current=1.0550,
        sl=0.0,
        tp=0.0,
        profit=50.0,
        swap=0.0,
        commission=-1.0,
        type=0,
        time_msc=1700000000000,
        identifier=12345,
        comment="",
    )
    payload = position_payload(row, strategy="test-strat", opened_at="2026-07-22T00:00:00Z")

    for field in ("realizedPnl", "riskAmount", "riskPct", "rMultiple", "mfe", "mae"):
        assert payload[field] is None, (
            f"open position mapping.{field} must be null, got {payload[field]!r}"
        )
