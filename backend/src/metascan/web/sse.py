from __future__ import annotations

# SSE Race-Free Splice implementation.
#
# Ordering invariant (SP2): SQLite commit MUST complete before EventBus publish.
# This is enforced by EventBus.publish/_publish_command_event which run
# journal.append/commit_bundle inside _publish_lock before _fanout.
#
# Handoff algorithm (SP4_DESIGN §3.2):
#   1. Under _publish_lock: subscribe + capture boundary (current max sequence).
#   2. Release lock.
#   3. Replay journal events > snapshot_sequence (or > boundary if resync).
#   4. Discard live-queue events where sequence <= boundary.
#   5. Stream live events from queue.
#
# Control frames (§3.3): connection stays OPEN on resync — generator continues.
# Reasons: GAP_DETECTED | QUEUE_OVERFLOW | BOOT_MISMATCH | INTERNAL_ERROR
#          | SEQUENCE_UNAVAILABLE (replay distance exceeds journal hard cap).
# Heartbeat: SSE comment ":\n\n" every 15 s when queue is idle.
#
# SSE connection counter: SseConnectionCounter tracks active connections so
# /v4/ops/metrics can report activeSseConnections accurately.

import asyncio
import json
import threading
from typing import AsyncGenerator

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal, READ_EVENTS_HARD_CAP

_RESYNC_REASONS = frozenset({
    "GAP_DETECTED",
    "QUEUE_OVERFLOW",
    "BOOT_MISMATCH",
    "INTERNAL_ERROR",
    "SEQUENCE_UNAVAILABLE",  # replay distance > journal hard cap READ_EVENTS_HARD_CAP
})
_HEARTBEAT_INTERVAL = 15.0


def _resync_frame(reason: str) -> str:
    assert reason in _RESYNC_REASONS, f"unknown resync reason: {reason}"
    return (
        f"event: system.resync.required\n"
        f"data: {json.dumps({'type': 'system.resync.required', 'reason': reason})}\n\n"
    )


def _event_frame(env) -> str:
    event_type = env.type.value if hasattr(env.type, "value") else str(env.type)
    return f"id: {env.sequence}\nevent: {event_type}\ndata: {env.model_dump_json(by_alias=True)}\n\n"


class SseConnectionCounter:
    """Thread-safe active SSE connection counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0

    def increment(self) -> None:
        with self._lock:
            self._count += 1

    def decrement(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def count(self) -> int:
        with self._lock:
            return self._count


# Module-level singleton — imported by health.py for ops/metrics.
active_sse_connections = SseConnectionCounter()


class SseHandoff:
    def __init__(self, bus: EventBus, journal: Journal) -> None:
        self._bus = bus
        self._journal = journal

    async def generate_stream(
        self,
        subscriber_id: str,
        client_boot_id: str,
        snapshot_sequence: int,
    ) -> AsyncGenerator[str, None]:
        # ── Step 1: under _publish_lock subscribe + capture boundary ──────────
        # Subscribe BEFORE yielding the initial ping so no events are missed.
        async with self._bus._publish_lock:
            sub = await self._bus.subscribe(subscriber_id)
            boundary = self._bus.sequence
            boot_id = self._bus.boot_id
        # ── Lock released ─────────────────────────────────────────────────────

        active_sse_connections.increment()
        try:
            yield ":\n\n"
            async for frame in self._stream_body(
                sub, boundary, boot_id, client_boot_id, snapshot_sequence, subscriber_id
            ):
                yield frame
        finally:
            active_sse_connections.decrement()
            # Unsubscribe without holding _publish_lock to avoid deadlock:
            # _fanout holds _publish_lock and calls put_nowait; if SSE finally
            # tried to acquire _publish_lock here we'd deadlock.
            # unsubscribe() is a plain dict.pop — no lock needed.
            await self._bus.unsubscribe(subscriber_id)

    async def _stream_body(
        self,
        sub,
        boundary: int,
        boot_id: str,
        client_boot_id: str,
        snapshot_sequence: int,
        subscriber_id: str,
    ) -> AsyncGenerator[str, None]:
        # ── Resync pre-checks ─────────────────────────────────────────────────
        resync_reason: str | None = None

        if client_boot_id == "BOOT_ID_UNKNOWN":
            if snapshot_sequence > 0:
                resync_reason = "BOOT_MISMATCH"
            snapshot_sequence = boundary
        elif client_boot_id != boot_id:
            resync_reason = "BOOT_MISMATCH"
            snapshot_sequence = boundary
        elif snapshot_sequence > boundary:
            resync_reason = "GAP_DETECTED"
            snapshot_sequence = boundary

        if resync_reason is not None:
            yield _resync_frame(resync_reason)
            # Connection stays open per §3.3 — continue to live streaming

        # ── Step 3: replay journal events snapshot_sequence < seq <= boundary ─
        if resync_reason is None and snapshot_sequence < boundary:
            replay_limit = boundary - snapshot_sequence
            # Guard: replay distance exceeds journal hard cap — cannot guarantee
            # complete replay; emit SEQUENCE_UNAVAILABLE (not INTERNAL_ERROR).
            if replay_limit > READ_EVENTS_HARD_CAP:
                yield _resync_frame("SEQUENCE_UNAVAILABLE")
            else:
                try:
                    old_events = self._journal.read_events(
                        boot_id,
                        after_sequence=snapshot_sequence,
                        limit=replay_limit,
                    )
                    # Fewer rows than expected → gap in journal
                    if len(old_events) < replay_limit:
                        yield _resync_frame("GAP_DETECTED")
                    else:
                        for env in old_events:
                            yield _event_frame(env)
                except Exception:
                    yield _resync_frame("INTERNAL_ERROR")

        # ── Steps 4+5: discard stale queue items, stream live events ──────────
        try:
            while True:
                try:
                    item = await asyncio.wait_for(sub.get(), timeout=_HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield ":\n\n"
                    continue

                kind = getattr(item, "kind", None)

                if kind == "bus_closed":
                    break

                if kind == "resync_required":
                    yield _resync_frame("QUEUE_OVERFLOW")
                    continue

                # Step 4: discard events already covered by replay
                if item.sequence <= boundary:
                    continue

                yield _event_frame(item)

        except Exception:
            yield _resync_frame("INTERNAL_ERROR")
            raise
