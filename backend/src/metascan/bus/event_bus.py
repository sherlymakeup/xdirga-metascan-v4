from __future__ import annotations

import asyncio
import functools
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.pipeline.request import InternalCommandRecord
from metascan.journal.commands import CommandTransitionRecord, build_transition_json
from metascan.journal.db import Journal

logger = logging.getLogger("metascan.bus")

RESYNC_KIND = "resync_required"
CLOSED_KIND = "bus_closed"
DEFAULT_SUBSCRIBER_MAXSIZE = 1024

QueueItem = "RuntimeEventEnvelope | ResyncMarker | ClosedMarker"


class EventBusClosed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResyncMarker:
    kind: str
    boot_id: str
    last_committed_sequence: int
    reason: str
    subscriber_id: str


@dataclass(frozen=True, slots=True)
class ClosedMarker:
    """Terminal control message: bus closed; unblocks waiters. Not journaled."""

    kind: str  # always CLOSED_KIND
    subscriber_id: str
    boot_id: str


class Subscription:
    def __init__(
        self,
        subscriber_id: str,
        queue: asyncio.Queue[RuntimeEventEnvelope | ResyncMarker | ClosedMarker],
        *,
        maxsize: int,
    ) -> None:
        self.id = subscriber_id
        self._queue = queue
        self._maxsize = maxsize
        self._lagging = False

    @property
    def is_lagging(self) -> bool:
        return self._lagging

    @property
    def maxsize(self) -> int:
        return self._maxsize

    async def get(
        self,
    ) -> RuntimeEventEnvelope | ResyncMarker | ClosedMarker:
        return await self._queue.get()

    def __aiter__(
        self,
    ) -> AsyncIterator[RuntimeEventEnvelope | ResyncMarker | ClosedMarker]:
        return self

    async def __anext__(
        self,
    ) -> RuntimeEventEnvelope | ResyncMarker | ClosedMarker:
        return await self.get()

    def ack_resync(self) -> None:
        self._lagging = False

    def _set_lagging(self, value: bool) -> None:
        self._lagging = value

    def _queue_ref(
        self,
    ) -> asyncio.Queue[RuntimeEventEnvelope | ResyncMarker | ClosedMarker]:
        return self._queue


class EventBus:
    def __init__(
        self,
        journal: Journal,
        *,
        default_queue_maxsize: int = DEFAULT_SUBSCRIBER_MAXSIZE,
    ) -> None:
        self._journal = journal
        self._default_maxsize = default_queue_maxsize
        self._publish_lock = asyncio.Lock()
        self._boot_id = ""
        self._sequence = 0
        self._revision = 0
        self._subs: dict[str, Subscription] = {}
        self._closed = False
        self._started = False

    @property
    def journal(self) -> Journal:
        return self._journal

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def lagging_subscriber_count(self) -> int:
        return sum(1 for s in self._subs.values() if s.is_lagging)

    async def start(self) -> None:
        if self._started:
            return
        if not self._journal.is_open:
            self._journal.open()
        self._boot_id = str(uuid.uuid4())
        self._sequence = 0
        self._revision = 0
        self._closed = False
        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with self._publish_lock:
            for sub in list(self._subs.values()):
                q = sub._queue_ref()
                while True:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                marker = ClosedMarker(
                    kind=CLOSED_KIND,
                    subscriber_id=sub.id,
                    boot_id=self._boot_id,
                )
                try:
                    q.put_nowait(marker)
                except asyncio.QueueFull:
                    # maxsize >= 1 after drain; should never happen
                    raise RuntimeError(
                        f"failed to enqueue ClosedMarker for subscriber {sub.id}"
                    ) from None
            self._subs.clear()
        if self._journal.is_open:
            self._journal.close()
        self._started = False

    async def subscribe(
        self, subscriber_id: str, maxsize: int | None = None
    ) -> Subscription:
        if self._closed:
            raise EventBusClosed("event bus closed")
        if subscriber_id in self._subs:
            raise ValueError(f"subscriber already exists: {subscriber_id}")
        ms = self._default_maxsize if maxsize is None else maxsize
        if ms < 1:
            raise ValueError("subscriber maxsize must be >= 1")
        q: asyncio.Queue[
            RuntimeEventEnvelope | ResyncMarker | ClosedMarker
        ] = asyncio.Queue(maxsize=ms)
        sub = Subscription(subscriber_id, q, maxsize=ms)
        self._subs[subscriber_id] = sub
        return sub

    async def unsubscribe(self, subscriber_id: str) -> None:
        self._subs.pop(subscriber_id, None)

    def _stamp(
        self, envelope: RuntimeEventEnvelope, *, mutates_state: bool
    ) -> tuple[RuntimeEventEnvelope, int, int]:
        prev_seq, prev_rev = self._sequence, self._revision
        self._sequence = prev_seq + 1
        if mutates_state:
            self._revision = prev_rev + 1
        stamped = envelope.model_copy(
            update={
                "boot_id": self._boot_id,
                "sequence": self._sequence,
                "revision": self._revision,
            }
        )
        return stamped, prev_seq, prev_rev

    def _restore(self, prev_seq: int, prev_rev: int) -> None:
        self._sequence = prev_seq
        self._revision = prev_rev

    def _fanout(self, stamped: RuntimeEventEnvelope) -> None:
        for sub in list(self._subs.values()):
            if sub.is_lagging:
                continue
            q = sub._queue_ref()
            try:
                q.put_nowait(stamped)
            except asyncio.QueueFull:
                self._overflow(sub, stamped)

    def _overflow(self, sub: Subscription, stamped: RuntimeEventEnvelope) -> None:
        q = sub._queue_ref()
        sub._set_lagging(True)
        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        marker = ResyncMarker(
            kind=RESYNC_KIND,
            boot_id=self._boot_id,
            last_committed_sequence=stamped.sequence,
            reason="subscriber_overflow",
            subscriber_id=sub.id,
        )
        try:
            q.put_nowait(marker)
        except asyncio.QueueFull as exc:
            # Invariant: after drain with maxsize>=1, put_nowait must succeed
            raise RuntimeError(
                f"resync marker enqueue failed for subscriber {sub.id}"
            ) from exc
        logger.warning(
            "subscriber_overflow subscriber_id=%s boot_id=%s sequence=%s maxsize=%s",
            sub.id,
            self._boot_id,
            stamped.sequence,
            sub.maxsize,
        )

    async def publish(
        self,
        envelope: RuntimeEventEnvelope,
        *,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(
                envelope, mutates_state=mutates_state
            )
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    self._journal.executor,
                    self._journal.append_event_committed,
                    stamped,
                )
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            self._fanout(stamped)
            return stamped

    async def publish_command_created(
        self,
        envelope: RuntimeEventEnvelope,
        status: RuntimeCommandStatus | InternalCommandRecord,
        request_json: str,
        *,
        origin: str = "TRANSPORT",
        execution_kind: str | None = None,
        internal_record_json: str | None = None,
    ) -> tuple[RuntimeCommandStatus | InternalCommandRecord, bool]:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(envelope, mutates_state=False)
            transition = CommandTransitionRecord(
                boot_id=stamped.boot_id, sequence=stamped.sequence, command_id=status.command_id,
                from_state=None, to_state="PREPARED", ts=status.updated_at,
                transition_json=build_transition_json(command_id=status.command_id, from_state=None, to_state="PREPARED", sequence=stamped.sequence),
            )
            loop = asyncio.get_running_loop()
            try:
                saved, created = await loop.run_in_executor(
                    self._journal.executor,
                    functools.partial(
                        self._journal.try_insert_command_create,
                        status,
                        transition,
                        stamped,
                        request_json,
                        origin=origin,
                        execution_kind=execution_kind,
                        internal_record_json=internal_record_json,
                    ),
                )
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            if not created:
                self._restore(prev_seq, prev_rev)
                return saved, False
            self._fanout(stamped)
            return saved, True

    async def publish_command_event(
        self,
        envelope: RuntimeEventEnvelope,
        status: RuntimeCommandStatus,
        *,
        from_state: str | None,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(
                envelope, mutates_state=mutates_state
            )
            to_state = str(
                status.state.value if hasattr(status.state, "value") else status.state
            )
            transition = CommandTransitionRecord(
                boot_id=stamped.boot_id,
                sequence=stamped.sequence,
                command_id=status.command_id,
                from_state=from_state,
                to_state=to_state,
                ts=status.updated_at,
                transition_json=build_transition_json(
                    command_id=status.command_id,
                    from_state=from_state,
                    to_state=to_state,
                    sequence=stamped.sequence,
                ),
            )
            loop = asyncio.get_running_loop()

            def _bundle() -> None:
                self._journal.commit_bundle(
                    envelope=stamped,
                    command_upsert=status,
                    transition=transition,
                )

            try:
                await loop.run_in_executor(self._journal.executor, _bundle)
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            self._fanout(stamped)
            return stamped

    async def publish_internal_command_event(
        self,
        envelope: RuntimeEventEnvelope,
        record: InternalCommandRecord,
        *,
        from_state: str | None,
        mutates_state: bool = True,
    ) -> RuntimeEventEnvelope:
        if self._closed or not self._started:
            raise EventBusClosed("event bus closed")
        async with self._publish_lock:
            stamped, prev_seq, prev_rev = self._stamp(
                envelope, mutates_state=mutates_state
            )
            to_state = str(record.state)
            transition = CommandTransitionRecord(
                boot_id=stamped.boot_id,
                sequence=stamped.sequence,
                command_id=record.command_id,
                from_state=from_state,
                to_state=to_state,
                ts=record.updated_at,
                transition_json=build_transition_json(
                    command_id=record.command_id,
                    from_state=from_state,
                    to_state=to_state,
                    sequence=stamped.sequence,
                ),
            )
            loop = asyncio.get_running_loop()

            def _bundle() -> None:
                self._journal.commit_internal_bundle(
                    envelope=stamped,
                    record=record,
                    transition=transition,
                    internal_record_json=record.internal_json(),
                )

            try:
                await loop.run_in_executor(self._journal.executor, _bundle)
            except Exception:
                self._restore(prev_seq, prev_rev)
                raise
            self._fanout(stamped)
            return stamped
