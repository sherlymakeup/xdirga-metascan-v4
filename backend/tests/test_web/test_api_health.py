from __future__ import annotations

# Tests for GET /v4/health and GET /v4/ops/metrics
# Contract source: HANDOFF.md §10.7, SP4_DESIGN §2.2.
# health: pure SLO probe — status, mt5_connected, db_ok, uptime.
# ops/metrics: backend ops detail — eventBusQueueSize, mt5PollLatencyMs, etc.

from types import SimpleNamespace

import pytest

from metascan.mt5.metrics import GatewayMetrics


@pytest.mark.asyncio
async def test_health_ok(async_client):
    r = await async_client.get("/v4/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "OK"
    assert d["db_ok"] is True
    assert d["mt5_connected"] is False
    assert isinstance(d["uptime"], float)


@pytest.mark.asyncio
async def test_health_no_auth_required(async_client):
    # health is a liveness probe — no auth gate per §10.7
    r = await async_client.get("/v4/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_metrics_reports_gateway_poll_latency(app_client):
    metrics = GatewayMetrics()
    metrics.record_cycle_ms(7.5)
    app_client._transport.app.state.metrics = metrics

    r = await app_client.get("/v4/ops/metrics")

    assert r.json()["mt5PollLatencyMs"] == 7.5


@pytest.mark.asyncio
async def test_health_reports_degraded_consumer_truthfully(app_client):
    app_client._transport.app.state.consumer = SimpleNamespace(connection_state="DEGRADED")

    r = await app_client.get("/v4/health")

    assert r.json()["status"] == "OK"
    assert r.json()["mt5_connected"] is False


@pytest.mark.asyncio
async def test_metrics_shape(async_client):
    r = await async_client.get("/v4/ops/metrics")
    assert r.status_code == 200
    d = r.json()
    assert "eventBusQueueSize" in d
    assert "mt5PollLatencyMs" in d
    assert "sqliteCommitLatencyMs" in d
    assert "activeSseConnections" in d
    assert isinstance(d["eventBusQueueSize"], int)
    assert isinstance(d["mt5PollLatencyMs"], float)
