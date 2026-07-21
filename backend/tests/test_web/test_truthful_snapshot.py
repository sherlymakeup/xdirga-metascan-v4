from __future__ import annotations

import pytest

from metascan.web.routers.snapshot import _empty_snapshot


def test_empty_snapshot_lastRunAt_is_null():
    snap = _empty_snapshot()
    assert snap["reconciliation"]["lastRunAt"] is None, (
        "empty snapshot must not contain a fabricated lastRunAt timestamp"
    )


def test_empty_snapshot_account_unavailable_fields_are_null():
    snap = _empty_snapshot()
    acc = snap["account"]
    for field in ("winRate", "profitFactor", "tradesToday", "dailyDrawdown", "maxDrawdown",
                  "grossExposure", "netExposure", "pendingOrders", "realizedPnlToday",
                  "realizedPnlWeek", "riskUtilization"):
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
