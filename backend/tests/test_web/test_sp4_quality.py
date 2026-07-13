from __future__ import annotations

# Tests for SP4 code-quality blockers (items 1-8).
# Each test cites the item number and contract source.

import asyncio
import json
import threading
import pytest

from metascan.contract.models import RuntimeEventEnvelope
from metascan.web.sse import SseHandoff, SseConnectionCounter, active_sse_connections, _RESYNC_REASONS


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_env(bus, seq: int, event_type: str = "runtime.state.changed") -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=f"evt-{seq}",
        type=event_type,
        runtime_id="xdirga",
        boot_id=bus.boot_id,
        sequence=seq,
        revision=seq,
        occurred_at="2026-07-13T00:00:00Z",
        emitted_at="2026-07-13T00:00:00Z",
        received_at="2026-07-13T00:00:00Z",
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload={"state": "IDLE"},
    )


def _make_trade_env(bus, seq: int, trade_id: str) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=f"trade-evt-{seq}",
        type="trade.closed",
        runtime_id="xdirga",
        boot_id=bus.boot_id,
        sequence=seq,
        revision=seq,
        occurred_at="2026-07-13T00:00:00Z",
        emitted_at="2026-07-13T00:00:00Z",
        received_at="2026-07-13T00:00:00Z",
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload={"tradeId": trade_id, "netPnl": 1.5},
    )


# ── Item 1: global 500 never exposes str(exc) ─────────────────────────────────

def test_global_500_no_exc_details():
    from fastapi import APIRouter
    from starlette.testclient import TestClient
    from metascan.web.app import create_app

    app = create_app()
    boom = APIRouter()

    @boom.get("/v4/boom-secret")
    async def _boom():
        raise RuntimeError("SECRET internal details xyz")

    app.include_router(boom)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/v4/boom-secret")
    assert r.status_code == 500
    body = r.text
    # Must not leak exception message
    assert "SECRET" not in body
    assert "internal details" not in body
    # Must have static contract fields only
    d = r.json()
    assert d["error"] == "Internal Server Error"
    assert d["code"] == "INTERNAL_ERROR"
    assert "details" not in d


# ── Item 2: hmac.compare_digest auth + sentinel return ───────────────────────

@pytest.mark.asyncio
async def test_auth_sentinel_not_raw_token(async_client):
    # verify_token must return opaque sentinel, not the raw token string
    from metascan.web.security import verify_token, _AUTH_OK
    assert _AUTH_OK == "AUTHENTICATED"
    # End-to-end: handshake returns 200 with correct token
    r = await async_client.get(
        "/v4/handshake", headers={"Authorization": "Bearer test-token-123"}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_timing_safe_wrong_token(async_client):
    # Wrong token → 401; timing-safe comparison via hmac.compare_digest
    r = await async_client.get(
        "/v4/handshake", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401


def test_auth_hmac_used():
    import inspect
    import metascan.web.security as sec_mod
    src = inspect.getsource(sec_mod)
    assert "hmac.compare_digest" in src


def test_auth_returns_sentinel_not_token():
    import metascan.web.security as sec_mod
    # _AUTH_OK sentinel is a non-secret string
    assert sec_mod._AUTH_OK != "test-token-123"
    assert sec_mod._AUTH_OK != ""


# ── Item 3: SEQUENCE_UNAVAILABLE when replay > hard cap ──────────────────────

@pytest.mark.asyncio
async def test_sequence_unavailable_reason_in_allowed_set():
    assert "SEQUENCE_UNAVAILABLE" in _RESYNC_REASONS


@pytest.mark.asyncio
async def test_sequence_unavailable_emitted_when_replay_exceeds_cap(event_bus, journal_db):
    from metascan.journal.db import READ_EVENTS_HARD_CAP
    # Simulate boundary far ahead of snapshot_sequence beyond hard cap
    # by setting snapshot_sequence = 0 and boundary = hard_cap + 1
    # We can't actually publish 10001 events, so we mock boundary directly.
    handoff = SseHandoff(event_bus, journal_db)

    # Subscribe manually to capture boundary=0, then manipulate
    async with event_bus._publish_lock:
        sub = await event_bus.subscribe("sub-sequnav")
        boundary = event_bus.sequence  # 0

    # Inject a fake large boundary by monkey-patching sequence counter
    # so replay_limit = boundary - snapshot_sequence > READ_EVENTS_HARD_CAP
    original_seq = event_bus._sequence
    event_bus._sequence = READ_EVENTS_HARD_CAP + 5

    try:
        gen = handoff.generate_stream("sub-sequnav2", event_bus.boot_id, 0)
        await anext(gen)  # ping (also re-subscribes under lock)
        frame = await anext(gen)
        assert "SEQUENCE_UNAVAILABLE" in frame
        assert "system.resync.required" in frame
    finally:
        event_bus._sequence = original_seq
        await event_bus.unsubscribe("sub-sequnav")
        await event_bus.unsubscribe("sub-sequnav2")


@pytest.mark.asyncio
async def test_no_internal_error_for_large_replay(event_bus, journal_db):
    from metascan.journal.db import READ_EVENTS_HARD_CAP
    handoff = SseHandoff(event_bus, journal_db)
    original_seq = event_bus._sequence
    event_bus._sequence = READ_EVENTS_HARD_CAP + 1
    try:
        gen = handoff.generate_stream("sub-nointernal", event_bus.boot_id, 0)
        await anext(gen)  # ping
        frame = await anext(gen)
        # Must be SEQUENCE_UNAVAILABLE, not INTERNAL_ERROR
        assert "SEQUENCE_UNAVAILABLE" in frame
        assert "INTERNAL_ERROR" not in frame
    finally:
        event_bus._sequence = original_seq
        await event_bus.unsubscribe("sub-nointernal")


# ── Item 4: transition.sequence == stamped event sequence ────────────────────

@pytest.mark.asyncio
async def test_command_transition_sequence_equals_event_sequence(async_client, journal_db):
    hdrs = {"Authorization": "Bearer test-token-123"}
    r = await async_client.post(
        "/v4/commands",
        json={"kind": "runtime.pause", "idempotencyKey": "idem-seq-check"},
        headers=hdrs,
    )
    assert r.status_code == 200
    cmd_id = r.json()["commandId"]

    # Query both tables and assert sequence equality
    def _check(conn):
        ev_row = conn.execute(
            "SELECT sequence FROM events WHERE type = 'command.created' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        tr_row = conn.execute(
            "SELECT sequence FROM command_transitions WHERE command_id = ?",
            (cmd_id,),
        ).fetchone()
        return ev_row, tr_row

    ev_row, tr_row = journal_db.run_on_writer(_check)
    assert ev_row is not None, "no event row found"
    assert tr_row is not None, "no transition row found"
    assert ev_row[0] == tr_row[0], (
        f"event.sequence={ev_row[0]} != transition.sequence={tr_row[0]}"
    )


@pytest.mark.asyncio
async def test_command_transition_sequence_nonzero(async_client, journal_db):
    hdrs = {"Authorization": "Bearer test-token-123"}
    r = await async_client.post(
        "/v4/commands",
        json={"kind": "runtime.start", "idempotencyKey": "idem-seq-nonzero"},
        headers=hdrs,
    )
    assert r.status_code == 200
    cmd_id = r.json()["commandId"]

    def _check(conn):
        return conn.execute(
            "SELECT sequence FROM command_transitions WHERE command_id = ?",
            (cmd_id,),
        ).fetchone()

    tr_row = journal_db.run_on_writer(_check)
    assert tr_row is not None
    # Sequence must be >= 1 (stamped, not placeholder 0)
    assert tr_row[0] >= 1, f"transition sequence is {tr_row[0]}, expected >= 1"


# ── Item 5: /history/trades reads journal trade.closed payloads ───────────────

@pytest.mark.asyncio
async def test_history_trades_returns_journal_data(async_client, event_bus, journal_db):
    hdrs = {"Authorization": "Bearer test-token-123"}

    # Publish two trade.closed events into the journal
    await event_bus.publish(_make_trade_env(event_bus, 1, "trade-aaa"))
    await event_bus.publish(_make_trade_env(event_bus, 2, "trade-bbb"))

    r = await async_client.get("/v4/history/trades", headers=hdrs)
    assert r.status_code == 200
    d = r.json()
    assert len(d["trades"]) == 2
    trade_ids = {t["tradeId"] for t in d["trades"]}
    assert "trade-aaa" in trade_ids
    assert "trade-bbb" in trade_ids


@pytest.mark.asyncio
async def test_history_trades_cursor_pagination(async_client, event_bus, journal_db):
    hdrs = {"Authorization": "Bearer test-token-123"}

    for i in range(3):
        await event_bus.publish(_make_trade_env(event_bus, i + 1, f"trade-pg-{i}"))

    # Fetch page of 2
    r = await async_client.get(
        "/v4/history/trades", params={"limit": 2}, headers=hdrs
    )
    assert r.status_code == 200
    d = r.json()
    assert len(d["trades"]) == 2
    assert d["nextCursor"] is not None

    # Fetch next page with cursor
    r2 = await async_client.get(
        "/v4/history/trades",
        params={"limit": 2, "cursor": d["nextCursor"]},
        headers=hdrs,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert len(d2["trades"]) == 1
    assert d2["nextCursor"] is None


@pytest.mark.asyncio
async def test_history_trades_no_non_trade_events(async_client, event_bus, journal_db):
    hdrs = {"Authorization": "Bearer test-token-123"}
    # Publish non-trade event
    await event_bus.publish(_make_env(event_bus, 1))
    await event_bus.publish(_make_trade_env(event_bus, 2, "trade-only"))

    r = await async_client.get("/v4/history/trades", headers=hdrs)
    assert r.status_code == 200
    d = r.json()
    # Only trade.closed events returned
    assert len(d["trades"]) == 1
    assert d["trades"][0]["tradeId"] == "trade-only"


# ── Item 6: activeSseConnections real counter ─────────────────────────────────

@pytest.mark.asyncio
async def test_sse_counter_increments_on_connect(event_bus, journal_db):
    counter = SseConnectionCounter()
    assert counter.count == 0
    counter.increment()
    assert counter.count == 1
    counter.decrement()
    assert counter.count == 0


@pytest.mark.asyncio
async def test_sse_counter_decrement_floor_zero():
    counter = SseConnectionCounter()
    counter.decrement()  # below zero should not go negative
    assert counter.count == 0


@pytest.mark.asyncio
async def test_ops_metrics_active_sse_count(async_client, event_bus, journal_db):
    # Before any SSE connections, counter should be 0
    r = await async_client.get("/v4/ops/metrics")
    assert r.status_code == 200
    assert r.json()["activeSseConnections"] == 0


@pytest.mark.asyncio
async def test_sse_handoff_increments_counter(event_bus, journal_db):
    initial = active_sse_connections.count
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-counter", event_bus.boot_id, 0)
    await anext(gen)  # ping — increment happens before first yield
    assert active_sse_connections.count == initial + 1
    # Close generator — decrement in finally
    await gen.aclose()
    assert active_sse_connections.count == initial


# ── Item 7: GatewayMetrics.note_cycle_overrun locked ─────────────────────────

def test_gateway_metrics_note_cycle_overrun():
    from metascan.mt5.metrics import GatewayMetrics
    m = GatewayMetrics()
    assert m.cycle_overruns == 0
    m.note_cycle_overrun()
    assert m.cycle_overruns == 1
    m.note_cycle_overrun()
    assert m.cycle_overruns == 2


def test_gateway_metrics_note_cycle_overrun_concurrent():
    from metascan.mt5.metrics import GatewayMetrics
    m = GatewayMetrics()
    threads = [threading.Thread(target=m.note_cycle_overrun) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.cycle_overruns == 100


def test_gateway_metrics_snapshot_consistent():
    from metascan.mt5.metrics import GatewayMetrics
    m = GatewayMetrics()
    m.note_cycle_overrun()
    m.note_handoff_drop()
    snap = m.snapshot()
    assert snap["cycle_overruns"] == 1
    assert snap["handoff_overruns"] == 1
    assert snap["handoff_dropped_count"] == 1
    assert snap["handoff_overrun_active"] is True


# ── Item 8: EventBus unsubscribe/close race — no deadlock ────────────────────

@pytest.mark.asyncio
async def test_sse_unsubscribe_no_deadlock_during_publish(event_bus, journal_db):
    # SSE finally calls unsubscribe (plain dict.pop); publish holds _publish_lock.
    # Verify no deadlock: publish while SSE generator is in finally.
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-nolock", event_bus.boot_id, 0)
    await anext(gen)  # ping + subscribe

    # Close generator (triggers finally → unsubscribe)
    close_task = asyncio.create_task(gen.aclose())
    # Publish concurrently — must not deadlock
    pub_task = asyncio.create_task(event_bus.publish(_make_env(event_bus, 1)))
    done, pending = await asyncio.wait(
        [close_task, pub_task], timeout=3.0
    )
    assert not pending, f"deadlock detected — tasks still pending: {pending}"
    for t in done:
        t.result()  # re-raise any exception


@pytest.mark.asyncio
async def test_bus_close_unsubscribes_cleanly(event_bus, journal_db):
    # Closing the bus while an SSE stream is active must not deadlock.
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-busclose", event_bus.boot_id, 0)
    await anext(gen)  # ping + subscribe

    # Close the bus — sends ClosedMarker to subscribers
    await asyncio.wait_for(event_bus.close(), timeout=3.0)

    # Generator should drain and stop cleanly
    frames = []
    try:
        async for frame in gen:
            frames.append(frame)
            if len(frames) > 20:
                break
    except StopAsyncIteration:
        pass
    # No exception; bus closed marker caused break in streaming loop


@pytest.mark.asyncio
async def test_unsubscribe_idempotent(event_bus):
    await event_bus.subscribe("sub-idem")
    await event_bus.unsubscribe("sub-idem")
    # Second unsubscribe must not raise
    await event_bus.unsubscribe("sub-idem")
