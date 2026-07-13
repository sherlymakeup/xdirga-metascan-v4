from __future__ import annotations

# Tests for app lifecycle — startup, exception handler, route census.
# Contract source: SP4_DESIGN §4.3, §4.2, HANDOFF.md §10.1.

import pytest
from metascan.web.app import create_app


def test_app_title():
    app = create_app()
    assert app.title == "XDirga Metascan V4"


def test_app_route_census():
    from fastapi.routing import APIRoute

    app = create_app()

    def collect(routes, prefix=""):
        paths = set()
        for route in routes:
            if isinstance(route, APIRoute):
                paths.add(prefix + route.path)
            elif type(route).__name__ == "_IncludedRouter":
                child_prefix = route.include_context.prefix
                paths |= collect(route.original_router.routes, prefix + child_prefix)
        return paths

    paths = collect(app.routes)

    # §10.1 exact nine /v4 routes (HANDOFF.md authoritative)
    expected = {
        "/v4/handshake",
        "/v4/capabilities",
        "/v4/snapshot",
        "/v4/commands",
        "/v4/commands/{command_id}",
        "/v4/events/stream",
        "/v4/history/trades",
        "/v4/health",
        "/v4/ops/metrics",  # SP4_DESIGN §2.2
    }
    assert paths == expected

    # Dead routes must not exist
    for dead in (
        "/v4/stream",
        "/v4/command",
        "/v4/journal/session",
        "/v4/journal/calendars",
        "/v4/journal/trades",
    ):
        assert dead not in paths, f"dead route still present: {dead}"


def test_global_exception_handler_shape():
    from fastapi import APIRouter
    from starlette.testclient import TestClient

    app = create_app()

    boom = APIRouter()

    @boom.get("/v4/test-boom")
    async def _boom():
        raise RuntimeError("intentional test error")

    app.include_router(boom)

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/v4/test-boom")
    assert r.status_code == 500
    d = r.json()
    assert "error" in d
    assert d["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_capabilities_endpoint(async_client):
    r = await async_client.get(
        "/v4/capabilities", headers={"Authorization": "Bearer test-token-123"}
    )
    assert r.status_code == 200
    d = r.json()
    assert "commands" in d
    # capabilitiesRevision: integer, matches runtime-types.ts RuntimeCapabilities.revision
    assert isinstance(d["revision"], int)
    assert d["source"] == "LOCAL_RUNTIME"
    assert isinstance(d["commands"], dict)
    # Safety-critical commands at riskLevel >= 3 per capabilities.py
    for kind in ("runtime.emergencyKill", "runtime.pause", "position.closeAll"):
        assert kind in d["commands"]
        assert d["commands"][kind]["riskLevel"] >= 3


@pytest.mark.asyncio
async def test_handshake_capabilities_revision(async_client):
    # RuntimeHandshake.capabilitiesRevision — integer per runtime-types.ts
    r = await async_client.get(
        "/v4/handshake", headers={"Authorization": "Bearer test-token-123"}
    )
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["capabilitiesRevision"], int)
    assert d["capabilitiesRevision"] >= 1
