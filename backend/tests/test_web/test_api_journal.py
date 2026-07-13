from __future__ import annotations

# Tests for GET /v4/history/trades — §10.6
# Contract source: HANDOFF.md §10.6, runtime-types.ts TradeHistoryPage.
# Also asserts /v4/journal/* routes are absent — they were in SP4_DESIGN §2.4
# but are NOT in the HANDOFF.md §10.1 authoritative endpoint table and were
# removed when the route census was corrected to §10.1.

import pytest


@pytest.mark.asyncio
async def test_history_trades_requires_auth(async_client):
    r = await async_client.get("/v4/history/trades")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_history_trades_empty_page(async_client):
    r = await async_client.get(
        "/v4/history/trades",
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 200
    d = r.json()
    # §10.6 TradeHistoryPage shape
    assert "trades" in d
    assert isinstance(d["trades"], list)
    assert d["nextCursor"] is None


@pytest.mark.asyncio
async def test_history_trades_limit_param(async_client):
    r = await async_client.get(
        "/v4/history/trades",
        params={"limit": 10},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_history_trades_limit_max(async_client):
    r = await async_client.get(
        "/v4/history/trades",
        params={"limit": 501},
        headers={"Authorization": "Bearer test-token-123"},
    )
    # limit > 500 should be rejected with 422
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_history_trades_cursor_param(async_client):
    r = await async_client.get(
        "/v4/history/trades",
        params={"cursor": "opaque-cursor-value"},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_old_journal_routes_removed(async_client):
    # §10.1 audit: /v4/journal/* routes are not in the authoritative endpoint table
    hdrs = {"Authorization": "Bearer test-token-123"}
    for path in ("/v4/journal/session", "/v4/journal/calendars", "/v4/journal/trades"):
        r = await async_client.get(path, headers=hdrs)
        assert r.status_code == 404, f"expected 404 for {path}, got {r.status_code}"
