from __future__ import annotations

# Tests for GET /v4/events/stream SSE — §10.5, SP4_DESIGN §3
# Contract source: HANDOFF.md §10.5, §3.1-3.3.
#
# Covers:
#   - Auth: token via ?token= (EventSource cannot set headers)
#   - bootId mismatch → 400 BOOT_MISMATCH (connection rejected)
#   - BOOT_ID_UNKNOWN with sequence>0 → BOOT_MISMATCH resync frame (stays open)
#   - sequence > boundary → GAP_DETECTED resync frame (stays open)
#   - QUEUE_OVERFLOW → resync frame (stays open)
#   - Race-free splice: replay then live events, no gap, no duplicate
#   - _publish_lock released before streaming
#   - Heartbeat comment frame on idle timeout
#   - Log token redaction
#   - /v4/snapshot auth + shape
#   - /v4/stream (old path) returns 404

import asyncio
import json
import logging
import pytest

from metascan.contract.hash import GOLDEN_SCHEMA_HASH
from metascan.contract.models import CockpitSnapshot, RuntimeEventEnvelope
from metascan.mt5.types import AccountRow, DashboardReadState, PositionRow, SymbolMeta, TickRow
from metascan.web.app import TokenRedactingFilter, create_app
from metascan.web.dependencies import get_bus, get_config, get_journal
from metascan.web.sse import SseHandoff


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_env(bus, seq: int) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=f"evt-{seq}",
        type="runtime.state.changed",
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


# ── snapshot ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_requires_auth(async_client):
    r = await async_client.get("/v4/snapshot")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_snapshot_shape(async_client):
    r = await async_client.get(
        "/v4/snapshot", headers={"Authorization": "Bearer FAKE-TEST-TOKEN-NOT-REAL"}
    )
    assert r.status_code == 200
    d = r.json()
    assert "metadata" in d
    assert "snapshot" in d
    assert d["metadata"]["protocolId"] == "xdirga-runtime-v4"
    assert d["metadata"]["schemaHash"] == GOLDEN_SCHEMA_HASH
    assert d["metadata"]["bootId"]
    assert d["metadata"]["source"] == "LOCAL_RUNTIME"


@pytest.mark.asyncio
async def test_snapshot_uses_retained_mt5_read_state(app_client):
    tick = TickRow("XAUUSDm", 2300.0, 2300.5, 2300.25, 1_700_000_000_000, 1.0)
    position = PositionRow(7, "XAUUSDm", 99, 0.2, 2300.0, 2301.0, 0.0, 2320.0, 10.0, -1.0, -0.5, 0, 1_700_000_000_000, 8, "manual")
    meta = SymbolMeta("XAUUSD", "XAUUSDm", 2, 0.01, 100.0, 0.01, 1.0, 0.01, 10.0, 0.01, 0, 0, 3, 4, True)
    state = DashboardReadState(
        connection_state="CONNECTED",
        account=AccountRow(1, 1000.0, 1010.0, 100.0, 910.0, 1010.0, "USD", 0, 2),
        positions=(position,),
        ticks={tick.symbol: tick},
        symbol_meta={meta.resolved: meta},
        bot_magic=240101,
        tick_age_budget_ms=1000.0,
        last_frame_id=3,
        last_frame_at="2026-07-20T00:00:00Z",
        poll_latency_ms=8.0,
    )
    app_client._transport.app.state.consumer = type(
        "ReadConsumer", (), {"dashboard_state": lambda self: state}
    )()

    r = await app_client.get(
        "/v4/snapshot", headers={"Authorization": "Bearer FAKE-TEST-TOKEN-NOT-REAL"}
    )

    snapshot = r.json()["snapshot"]
    assert snapshot["broker"]["connection"] == "CONNECTED"
    assert snapshot["broker"]["avgLatencyMs"] == 8.0
    assert snapshot["account"]["equity"] == 1010.0
    assert snapshot["account"]["freshness"] == "FRESH"
    assert snapshot["positions"][0]["brokerTicket"] == "7"
    assert snapshot["positions"][0]["ownership"] == "FOREIGN"
    assert snapshot["positions"][0]["strategy"] is None
    assert snapshot["positions"][0]["riskAmount"] is None
    assert snapshot["positions"][0]["stopLoss"] is None
    assert snapshot["positions"][0]["protection"] == "PARTIALLY_PROTECTED"
    assert snapshot["positions"][0]["netPnl"] == 8.5
    assert snapshot["positions"][0]["openedAt"] == "2023-11-14T22:13:20Z"
    market = snapshot["markets"][0]
    assert market["symbol"] == "XAUUSDm"
    assert market["bid"] == 2300.0
    assert market["spread"] == 0.5
    assert market["contractSize"] == 100.0
    assert market["group"] is None
    assert market["changePct"] is None
    assert market["sessionOpen"] is None
    assert market["swapLong"] is None
    assert market["marginRequirement"] is None
    assert snapshot["account"]["floatingPnl"] == 10.0
    assert snapshot["broker"]["lastTickAt"] == "2023-11-14T22:13:20Z"
    assert snapshot["runtime"]["state"] == "READY"
    CockpitSnapshot.model_validate(snapshot)


@pytest.mark.asyncio
async def test_snapshot_captures_state_and_cursor_under_publication_boundary(event_bus):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_publication() -> None:
        async with event_bus._publish_lock:
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold_publication())
    await entered.wait()
    try:
        capture = asyncio.create_task(event_bus.capture_boundary(lambda: "atomic-state"))
        await asyncio.sleep(0)
        assert capture.done() is False
    finally:
        release.set()
        await holder

    state, boot_id, revision, sequence = await capture
    assert state == "atomic-state"
    assert (boot_id, revision, sequence) == (event_bus.boot_id, event_bus.revision, event_bus.sequence)


# ── old path not exposed ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_old_stream_path_not_exposed(async_client):
    # §10.1: path is /v4/events/stream — /v4/stream must not exist
    r = await async_client.get("/v4/stream")
    assert r.status_code == 404


# ── log redaction ─────────────────────────────────────────────────────────────

def test_log_token_redaction():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="t.py", lineno=1,
        msg="GET /v4/events/stream?token=secret-abc-123&bootId=xyz",
        args=(), exc_info=None,
    )
    f = TokenRedactingFilter()
    assert f.filter(record) is True
    assert "secret-abc-123" not in record.msg
    assert "token=***" in record.msg


def test_log_token_redaction_in_args():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="t.py", lineno=1,
        msg="request: %s",
        args=("token=supersecret",),
        exc_info=None,
    )
    f = TokenRedactingFilter()
    f.filter(record)
    assert "supersecret" not in str(record.args)
    assert "token=***" in str(record.args)


# ── bootId mismatch → 400 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_boot_id_mismatch_rejected(async_client):
    r = await async_client.get(
        "/v4/events/stream",
        params={"bootId": "wrong-boot-id", "sequence": 0, "token": "FAKE-TEST-TOKEN-NOT-REAL"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "BOOT_MISMATCH"


# ── ASGI harness: stream returns 200 text/event-stream ───────────────────────

@pytest.mark.asyncio
async def test_stream_200_text_event_stream(test_config, event_bus, journal_db):
    app = create_app()
    app.dependency_overrides[get_config] = lambda: test_config
    app.dependency_overrides[get_bus] = lambda: event_bus
    app.dependency_overrides[get_journal] = lambda: journal_db

    boot_id = event_bus.boot_id
    qs = f"token=FAKE-TEST-TOKEN-NOT-REAL&bootId={boot_id}&sequence=0".encode()

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/v4/events/stream",
        "raw_path": b"/v4/events/stream",
        "query_string": qs,
        "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
    }

    recv_q: asyncio.Queue = asyncio.Queue()
    await recv_q.put({"type": "http.request", "body": b"", "more_body": False})

    sent = []

    async def _receive():
        return await recv_q.get()

    async def _send(msg):
        sent.append(msg)
        if msg["type"] == "http.response.body" and msg.get("body"):
            await recv_q.put({"type": "http.disconnect"})

    try:
        await asyncio.wait_for(app(scope, _receive, _send), timeout=5.0)
    except (asyncio.CancelledError, Exception):
        pass

    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    assert start is not None
    assert start["status"] == 200
    ct = dict(start["headers"]).get(b"content-type", b"")
    assert b"text/event-stream" in ct

    body_msgs = [m for m in sent if m["type"] == "http.response.body"]
    assert body_msgs
    assert b":" in body_msgs[0]["body"]


# ── SseHandoff unit tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handoff_initial_ping(event_bus, journal_db):
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-ping", event_bus.boot_id, 0)
    ping = await anext(gen)
    assert ping == ":\n\n"
    await event_bus.unsubscribe("sub-ping")


@pytest.mark.asyncio
async def test_handoff_lock_released_after_subscribe(event_bus, journal_db):
    # _publish_lock must be released before streaming begins
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-lock", event_bus.boot_id, 0)
    await anext(gen)  # initial ping
    assert not event_bus._publish_lock.locked()
    await event_bus.unsubscribe("sub-lock")


@pytest.mark.asyncio
async def test_handoff_replay_then_live(event_bus, journal_db):
    await event_bus.publish(_make_env(event_bus, 1))

    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-replay", event_bus.boot_id, 0)

    ping = await anext(gen)
    assert ping == ":\n\n"

    # Journal replay of seq=1
    replayed = await anext(gen)
    assert "evt-1" in replayed

    # Publish live event after handoff
    await event_bus.publish(_make_env(event_bus, 2))
    live = await asyncio.wait_for(anext(gen), timeout=2.0)
    assert "evt-2" in live

    await event_bus.unsubscribe("sub-replay")


@pytest.mark.asyncio
async def test_handoff_no_duplicate_at_boundary(event_bus, journal_db):
    await event_bus.publish(_make_env(event_bus, 1))
    boundary = event_bus.sequence  # == 1

    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-nodup", event_bus.boot_id, 0)
    await anext(gen)  # ping

    # Replay gives seq=1
    r = await anext(gen)
    assert "evt-1" in r

    # Publish seq=2 after boundary
    await event_bus.publish(_make_env(event_bus, 2))
    live = await asyncio.wait_for(anext(gen), timeout=2.0)
    assert "evt-2" in live
    assert "evt-1" not in live  # no duplication

    await event_bus.unsubscribe("sub-nodup")


@pytest.mark.asyncio
async def test_handoff_boot_id_unknown_seq_zero_no_resync(event_bus, journal_db):
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-unknown-0", "BOOT_ID_UNKNOWN", 0)
    ping = await anext(gen)
    assert ping == ":\n\n"
    # No resync frame since snapshot_sequence=0 (treated as fresh connect)
    await event_bus.publish(_make_env(event_bus, 1))
    live = await asyncio.wait_for(anext(gen), timeout=2.0)
    assert "evt-1" in live
    await event_bus.unsubscribe("sub-unknown-0")


@pytest.mark.asyncio
async def test_handoff_boot_id_unknown_seq_nonzero_resync(event_bus, journal_db):
    # BOOT_ID_UNKNOWN + sequence>0 → BOOT_MISMATCH resync, connection stays open
    await event_bus.publish(_make_env(event_bus, 1))
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-unknown-seq", "BOOT_ID_UNKNOWN", 1)
    await anext(gen)  # ping
    frame = await anext(gen)
    assert "system.resync.required" in frame
    assert "BOOT_MISMATCH" in frame
    # Stream keeps going after resync
    await event_bus.publish(_make_env(event_bus, 2))
    live = await asyncio.wait_for(anext(gen), timeout=2.0)
    assert "evt-2" in live
    await event_bus.unsubscribe("sub-unknown-seq")


@pytest.mark.asyncio
async def test_handoff_gap_detected_resync(event_bus, journal_db):
    # snapshot_sequence > boundary → GAP_DETECTED, stays open
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-gap", event_bus.boot_id, 9999)
    await anext(gen)  # ping
    frame = await anext(gen)
    assert "system.resync.required" in frame
    assert "GAP_DETECTED" in frame
    # Still alive: publish and receive live event
    await event_bus.publish(_make_env(event_bus, 1))
    live = await asyncio.wait_for(anext(gen), timeout=2.0)
    assert "evt-1" in live
    await event_bus.unsubscribe("sub-gap")


@pytest.mark.asyncio
async def test_handoff_queue_overflow_resync(event_bus, journal_db):
    # Pre-subscribe with maxsize=1, overflow → QUEUE_OVERFLOW resync frame
    sub = await event_bus.subscribe("sub-overflow", maxsize=1)
    await event_bus.publish(_make_env(event_bus, 1))
    await event_bus.publish(_make_env(event_bus, 2))  # triggers overflow on sub-overflow

    item = await sub.get()
    assert item.kind == "resync_required"
    await event_bus.unsubscribe("sub-overflow")


@pytest.mark.asyncio
async def test_sse_frame_format(event_bus, journal_db):
    # Each frame: id=sequence, event=type, data=JSON envelope
    await event_bus.publish(_make_env(event_bus, 1))
    handoff = SseHandoff(event_bus, journal_db)
    gen = handoff.generate_stream("sub-fmt", event_bus.boot_id, 0)
    await anext(gen)  # ping
    frame = await anext(gen)
    assert frame.startswith("id: 1\n")
    assert "event: runtime.state.changed\n" in frame
    assert "data: " in frame
    data_line = [l for l in frame.splitlines() if l.startswith("data: ")][0]
    parsed = json.loads(data_line[len("data: "):])
    assert parsed["eventId"] == "evt-1"
    await event_bus.unsubscribe("sub-fmt")
