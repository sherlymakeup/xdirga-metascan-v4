from __future__ import annotations

# Tests for POST /v4/commands and GET /v4/commands/{commandId} — §10.4, §10.1
# Contract source: HANDOFF.md §10.4, runtime-types.ts CommandAccepted/RuntimeCommandStatus.
#
# Idempotency rule: identical idempotencyKey returns SAME commandId + current state.
# SP4 constraint: no MT5 execution occurs.

import pytest


@pytest.mark.asyncio
async def test_submit_command_requires_auth(async_client):
    # HANDOFF.md §10: REST endpoints require Authorization: Bearer.
    r = await async_client.post("/v4/commands", json={
        "kind": "runtime.pause",
        "idempotencyKey": "idem-auth-test",
        "correlationId": "corr-auth-test",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_submit_command_accepted(async_client, journal_db):
    payload = {
        "kind": "runtime.pause",
        "idempotencyKey": "idem-1",
        "correlationId": "corr-1",
        "clientRequestId": "req-1",
    }
    r = await async_client.post(
        "/v4/commands",
        json=payload,
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 200
    d = r.json()
    # §10.4 CommandCreated shape (SP5: initial state is PREPARED)
    assert d["state"] == "PREPARED"
    assert "commandId" in d
    assert d["idempotencyKey"] == "idem-1"
    assert "receivedAt" in d

    # Persisted in journal
    row = journal_db.run_on_writer(
        lambda conn: conn.execute(
            "SELECT state FROM commands WHERE command_id = ?", (d["commandId"],)
        ).fetchone()
    )
    assert row is not None
    assert row[0] == "PREPARED"


@pytest.mark.asyncio
async def test_submit_command_idempotency(async_client):
    payload = {
        "kind": "runtime.pause",
        "idempotencyKey": "idem-2",
        "correlationId": "corr-2",
    }
    hdrs = {"Authorization": "Bearer test-token-123"}

    r1 = await async_client.post("/v4/commands", json=payload, headers=hdrs)
    assert r1.status_code == 200
    cmd_id1 = r1.json()["commandId"]

    # Identical idempotencyKey → same commandId, no new record
    r2 = await async_client.post("/v4/commands", json=payload, headers=hdrs)
    assert r2.status_code == 200
    assert r2.json()["commandId"] == cmd_id1
    assert r2.json()["idempotencyKey"] == "idem-2"


@pytest.mark.asyncio
async def test_get_command_by_id(async_client):
    hdrs = {"Authorization": "Bearer test-token-123"}
    payload = {
        "kind": "runtime.reconcile",
        "idempotencyKey": "idem-get-1",
        "correlationId": "corr-get-1",
    }
    r = await async_client.post("/v4/commands", json=payload, headers=hdrs)
    assert r.status_code == 200
    cmd_id = r.json()["commandId"]

    r2 = await async_client.get(f"/v4/commands/{cmd_id}", headers=hdrs)
    assert r2.status_code == 200
    d = r2.json()
    assert d["commandId"] == cmd_id
    assert d["state"] == "PREPARED"
    assert d["kind"] == "runtime.reconcile"
    assert d["idempotencyKey"] == "idem-get-1"


@pytest.mark.asyncio
async def test_get_command_not_found(async_client):
    r = await async_client.get(
        "/v4/commands/nonexistent-id",
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_submit_command_no_mt5_execution(async_client):
    # SP5: submission must not mutate MT5 state; just journaled as PREPARED
    r = await async_client.post(
        "/v4/commands",
        json={"kind": "position.closeAll", "idempotencyKey": "idem-safety-1"},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "PREPARED"
