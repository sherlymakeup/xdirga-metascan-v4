from __future__ import annotations

# Tests for GET /v4/handshake — §10.2
# Contract source: HANDOFF.md §10.2, runtime-contract.ts EXPECTED_RUNTIME_CONTRACT.

import pytest
from metascan.contract.hash import GOLDEN_SCHEMA_HASH
from metascan.contract.commands import RUNTIME_COMMAND_KINDS


@pytest.mark.asyncio
async def test_handshake_requires_auth(async_client):
    r = await async_client.get("/v4/handshake")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_handshake_contract_shape(async_client):
    r = await async_client.get(
        "/v4/handshake", headers={"Authorization": "Bearer FAKE-TEST-TOKEN-NOT-REAL"}
    )
    assert r.status_code == 200
    d = r.json()

    # §10.2 required fields
    assert d["runtimeName"] == "XDirga Runtime V4"
    assert d["protocolId"] == "xdirga-runtime-v4"
    assert d["protocolVersion"] == "4.1.0"
    assert d["schemaVersion"] == "1.1.0"
    assert d["schemaHash"] == GOLDEN_SCHEMA_HASH
    assert d["minFrontendVersion"] == "1.0.0"
    assert d["brokerProvider"] == "EXNESS"
    assert d["brokerEnvironment"] == "TRIAL"
    assert d["executionSemantics"] == "LIVE"
    assert d["source"] == "LOCAL_RUNTIME"

    # bootId and runtimeId present
    assert d["bootId"]
    assert d["runtimeId"] == "xdirga"

    # supportedCommands covers full catalog
    assert set(RUNTIME_COMMAND_KINDS).issubset(set(d["supportedCommands"]))

    # supportedFeatures
    assert "runtime.safety" in d["supportedFeatures"]
    assert "trade.history" in d["supportedFeatures"]


@pytest.mark.asyncio
async def test_handshake_token_via_query(async_client):
    r = await async_client.get("/v4/handshake", params={"token": "FAKE-TEST-TOKEN-NOT-REAL"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_handshake_wrong_token(async_client):
    r = await async_client.get(
        "/v4/handshake", headers={"Authorization": "Bearer wrong-token"}
    )
    assert r.status_code == 401
