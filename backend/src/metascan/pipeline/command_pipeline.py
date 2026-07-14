from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from metascan.bus.event_bus import EventBus
from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.pipeline.command_queue import CommandQueueFull
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.request import CommandRequest, InternalCommandRecord, InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.risk_gate import classify, run_gates

logger = logging.getLogger("metascan.pipeline.command_pipeline")

CONTROL_KINDS = frozenset({"runtime.start", "runtime.resume", "runtime.emergencyKill", "runtime.disableEntries", "runtime.enableEntries", "order.cancel", "order.cancelAll", "position.close", "position.closePartial", "position.modifyProtection", "position.closeAll"})
MUTATION_KINDS = frozenset({"position.close", "position.closePartial", "position.modifyProtection", "order.cancel", "INTERNAL_ENTRY_MARKET"})
TERMINAL = frozenset({"COMPLETED", "FAILED", "EXECUTION_UNKNOWN", "CANCELLED"})


def verdict(kind: str, verify_result: dict[str, Any]) -> tuple[bool | None, str | None]:
    """Return (executed, reason) per-kind verification verdict table.

    executed=True → COMPLETED, executed=False → FAILED, executed=None → keep EXECUTION_UNKNOWN.

    close:       executed iff target position ABSENT
    closePartial: executed iff volume reduced
    modifyProtection: executed iff SL/TP changed to expected
    order.cancel:    executed iff order absent
    INTERNAL_ENTRY_MARKET: executed iff position exists (deal+position correlation)
    """
    positions = tuple(verify_result.get("positions") or ())
    deals = tuple(verify_result.get("deals") or ())
    position_exists = verify_result.get("positionExists")
    order_exists = verify_result.get("orderExists")
    ticket = verify_result.get("ticket")

    if kind in ("position.close",):
        if position_exists is False:
            return True, None
        if position_exists is True:
            return False, "BROKER_REJECTED"
        return None, None

    if kind == "position.closePartial":
        pre_vol = verify_result.get("pre_volume") or verify_result.get("preVolume")
        post_vol = verify_result.get("post_volume") or verify_result.get("postVolume")
        partial_executed = verify_result.get("partial_executed") if "partial_executed" in verify_result else verify_result.get("partialExecuted")
        if partial_executed is True:
            return True, None
        if partial_executed is False:
            return False, "BROKER_REJECTED"
        if pre_vol is not None and post_vol is not None:
            if post_vol < pre_vol:
                return True, None
            return False, "BROKER_REJECTED"
        return None, None

    if kind == "position.modifyProtection":
        executed = verify_result.get("modify_executed") if "modify_executed" in verify_result else verify_result.get("modifyExecuted")
        if executed is True:
            return True, None
        if executed is False:
            return False, "BROKER_REJECTED"
        return None, None

    if kind == "order.cancel":
        if order_exists is False:
            return True, None
        if order_exists is True:
            return False, "BROKER_REJECTED"
        return None, None

    if kind == "INTERNAL_ENTRY_MARKET":
        if position_exists is True:
            return True, None
        if position_exists is False:
            return False, "BROKER_REJECTED"
        return None, None

    return None, None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class QueuedCommand:
    status: RuntimeCommandStatus | InternalCommandRecord
    request: CommandRequest | InternalEntryRequest
    origin: str


class CommandPipeline:
    def __init__(self, *, bus: EventBus, gateway: Any, risk_config: RiskConfig, facts: RuntimeFactsProvider, bot_magic: int, pending: PendingIntentRegistry | None = None, runtime_id: str = "xdirga", journal: Any = None) -> None:
        if bot_magic <= 0:
            raise ValueError("bot_magic must be a positive nonzero integer")
        self._bus, self._gateway, self._risk_config, self._pending, self._facts = bus, gateway, risk_config, pending or PendingIntentRegistry(), facts
        self._runtime_id, self._bot_magic = runtime_id, bot_magic
        self._queue: asyncio.Queue[QueuedCommand] = asyncio.Queue(maxsize=risk_config.queue_size)
        self._task: asyncio.Task[None] | None = None
        self._locks: set[str] = set()
        self.entries_enabled = True
        self.halted = False
        self._journal = journal or (bus._journal if hasattr(bus, "_journal") else None)
        self._healthy = True
        self._failure_reason: str | None = None

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def mutation_in_flight(self) -> bool:
        return bool(self._locks)

    def start(self) -> None:
        self._recover_runtime_state()
        self._recover_entry_intents()
        if self._task is None: self._task = asyncio.create_task(self._run())

    def _recover_runtime_state(self) -> None:
        if self._journal is None:
            return
        try:
            row = self._journal.run_on_writer(
                lambda conn: conn.execute("SELECT value FROM runtime_state WHERE key='halted'").fetchone()
            )
        except Exception:
            return
        if row and str(row[0]) == "1":
            self.halted = True
        try:
            row2 = self._journal.run_on_writer(
                lambda conn: conn.execute("SELECT value FROM runtime_state WHERE key='entries_enabled'").fetchone()
            )
        except Exception:
            return
        if row2 and str(row2[0]) == "0":
            self.entries_enabled = False

    def _persist_runtime_state(self, *, halted: bool, entries_enabled: bool) -> None:
        if self._journal is None:
            return
        try:
            self._journal.run_on_writer(lambda conn: (
                conn.execute("INSERT OR REPLACE INTO runtime_state (key, value) VALUES ('halted', ?)", ("1" if halted else "0",)),
                conn.execute("INSERT OR REPLACE INTO runtime_state (key, value) VALUES ('entries_enabled', ?)", ("1" if entries_enabled else "0",)),
                conn.commit(),
            ))
        except Exception:
            pass

    def _recover_entry_intents(self) -> None:
        if self._journal is None:
            return
        try:
            intents = self._journal.recover_entry_intents()
        except Exception:
            return
        for intent in intents:
            scope = f"entry:{intent['symbol']}"
            self._locks.add(scope)
            self._pending.register_entry(str(intent["symbol"]), str(intent["command_id"]))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task = None

    def enqueue(self, status: RuntimeCommandStatus | InternalCommandRecord, request: CommandRequest | InternalEntryRequest, *, origin: str) -> None:
        try: self._queue.put_nowait(QueuedCommand(status, request, origin))
        except asyncio.QueueFull as exc: raise CommandQueueFull("Command queue full") from exc

    async def submit_internal(self, request: InternalEntryRequest, *, idempotency_key: str, correlation_id: str | None = None) -> InternalCommandRecord:
        now, command_id, correlation = _now(), str(uuid.uuid4()), correlation_id or str(uuid.uuid4())
        record = request.to_internal_record(command_id=command_id, client_request_id=str(uuid.uuid4()), idempotency_key=idempotency_key, correlation_id=correlation, created_at=now)
        envelope = self._envelope(record, "command.created", "PREPARED", None, {"kind": "INTERNAL_ENTRY_MARKET"})
        saved, created = await self._bus.publish_command_created(envelope, record, request.canonical_json(), origin="INTERNAL", execution_kind="INTERNAL_ENTRY_MARKET", internal_record_json=record.internal_json())
        assert isinstance(saved, InternalCommandRecord)
        if created: self.enqueue(saved, request, origin="INTERNAL")
        return saved

    async def submit_transport(self, request: CommandRequest, *, idempotency_key: str, correlation_id: str | None = None) -> RuntimeCommandStatus:
        now, command_id, correlation = _now(), str(uuid.uuid4()), correlation_id or str(uuid.uuid4())
        status = RuntimeCommandStatus(command_id=command_id, client_request_id=str(uuid.uuid4()), correlation_id=correlation, idempotency_key=idempotency_key, kind=request.kind, target_id=request.target_id, state="PREPARED", created_at=now, updated_at=now)
        envelope = self._envelope(status, "command.created", "PREPARED", None, {"kind": request.kind})
        saved, created = await self._bus.publish_command_created(envelope, status, request.canonical_json(), origin="TRANSPORT")
        assert isinstance(saved, RuntimeCommandStatus)
        if created: self.enqueue(saved, request, origin="TRANSPORT")
        return saved

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._process(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.critical("Pipeline command crashed: command_id=%s kind=%s origin=%s",
                                getattr(item.status, "command_id", "?"), getattr(item.request, "kind", "?"), item.origin)
                await self._fail_with_internal_error(item)
                self._queue.task_done()

    async def _fail_with_internal_error(self, item: QueuedCommand) -> None:
        try:
            if isinstance(item.status, InternalCommandRecord):
                await self._transition_internal(item.status, "FAILED", reason="BROKER_REJECTED", event_type="command.failed")
            else:
                await self._transition(item.status, "FAILED", reason="BROKER_REJECTED", event_type="command.failed")
            alert = RuntimeEventEnvelope(
                event_id=str(uuid.uuid4()), type="alert.created",
                runtime_id=self._runtime_id, boot_id=self._bus.boot_id,
                sequence=0, revision=0, occurred_at=_now(), emitted_at=_now(),
                received_at=_now(), severity="CRITICAL",
                source="LOCAL_RUNTIME", command_id=item.status.command_id,
                payload={"commandId": item.status.command_id, "reason": "PIPELINE_INTERNAL_ERROR"},
            )
            await self._bus.publish(alert, mutates_state=False)
        except Exception:
            self._healthy = False
            self._failure_reason = "PIPELINE_INTERNAL_ERROR: transition/alert infrastructure failed"
            logger.critical("Pipeline infrastructure failure: %s", self._failure_reason)
            raise

    def _envelope(self, status: RuntimeCommandStatus | InternalCommandRecord, event_type: str, state: str, reason: str | None, extra: dict[str, Any] | None = None) -> RuntimeEventEnvelope:
        now = _now()
        kind = status.kind if isinstance(status, InternalCommandRecord) else getattr(status, "kind", "unknown")
        payload: dict[str, Any] = {"commandId": status.command_id, "state": state, "reason": reason, "kind": kind}
        if extra: payload.update(extra)
        return RuntimeEventEnvelope(event_id=str(uuid.uuid4()), type=event_type, runtime_id=self._runtime_id, boot_id=self._bus.boot_id, sequence=0, revision=0, occurred_at=now, emitted_at=now, received_at=now, severity="CRITICAL" if state == "EXECUTION_UNKNOWN" else "INFO", source="LOCAL_RUNTIME", correlation_id=status.correlation_id, command_id=status.command_id, payload=payload)

    async def _transition(self, status: RuntimeCommandStatus, state: str, *, reason: str | None = None, event_type: str | None = None, extra: dict[str, Any] | None = None) -> RuntimeCommandStatus:
        updated = status.model_copy(update={"state": state, "reason": reason, "updated_at": _now(), "completed_at": _now() if state in TERMINAL else None})
        if event_type: await self._bus.publish_command_event(self._envelope(updated, event_type, state, reason, extra), updated, from_state=str(status.state), mutates_state=state in TERMINAL)
        return updated

    async def _transition_internal(self, record: InternalCommandRecord, state: str, *, reason: str | None = None, event_type: str | None = None, extra: dict[str, Any] | None = None) -> InternalCommandRecord:
        updated = InternalCommandRecord(command_id=record.command_id, client_request_id=record.client_request_id, idempotency_key=record.idempotency_key, correlation_id=record.correlation_id, kind=record.kind, target_id=record.target_id, state=state, created_at=record.created_at, updated_at=_now(), origin=record.origin, execution_kind=record.execution_kind, request_json=record.request_json, progress=record.progress, current_step=record.current_step, message=record.message, error_code=record.error_code)
        if event_type: await self._bus.publish_internal_command_event(self._envelope(updated, event_type, state, reason, extra), updated, from_state=str(record.state), mutates_state=state in TERMINAL)
        return updated

    async def _process(self, item: QueuedCommand) -> None:
        status, request, origin = item.status, item.request, item.origin
        if isinstance(status, InternalCommandRecord):
            internal_record = status
            kind = "INTERNAL_ENTRY_MARKET"
        else:
            internal_record = None
            kind = request.kind
        if internal_record is not None:
            internal_record = await self._transition_internal(internal_record, "SUBMITTING")
            status = internal_record
        else:
            status = await self._transition(status, "SUBMITTING")
        if origin == "TRANSPORT" and kind not in RUNTIME_COMMAND_KINDS:
            await self._transition(status, "FAILED", reason="UNSUPPORTED_COMMAND", event_type="command.failed"); return
        if origin == "TRANSPORT" and kind not in CONTROL_KINDS:
            await self._transition(status, "FAILED", reason="UNSUPPORTED_COMMAND", event_type="command.failed"); return
        classified = classify(kind)
        if classified is None:
            await self._transition(status, "FAILED", reason="SAFETY_CLASSIFICATION_FAILED", event_type="command.failed"); return
        scope = self._scope(kind, request, status)
        if scope in self._locks:
            await self._transition(status, "FAILED", reason="MUTATION_SCOPE_LOCKED", event_type="command.failed", extra={"classification": classified[0], "targetScope": scope}); return
        if kind == "INTERNAL_ENTRY_MARKET":
            if self.halted or not self.entries_enabled:
                await self._transition_internal(internal_record, "FAILED", reason="ENTRY_NOT_ELIGIBLE", event_type="command.failed"); return
            assert isinstance(request, InternalEntryRequest)
            result = run_gates(request, self._facts.snapshot(), self._risk_config, self._facts)
            if not result.passed:
                await self._transition(status, "FAILED", reason=result.reason, event_type="command.failed", extra={"classification": result.classification, "gate": result.trace[-1], "targetScope": result.target_scope}); return
            payload = {"symbol": request.symbol, "side": request.side, "stop_loss": request.stopLoss, "take_profit": request.takeProfit, "volume": result.volume, "deviation": self._risk_config.deviation_points}
        else:
            payload = request.model_dump(exclude_none=True)
            self._locks.add(scope)
        if kind == "runtime.emergencyKill": await self._emergency(status, origin); return
        if kind in {"runtime.disableEntries", "runtime.enableEntries", "runtime.start", "runtime.resume"}:
            self.entries_enabled = kind != "runtime.disableEntries"
            self.halted = False if kind in {"runtime.start", "runtime.resume"} else self.halted
            self._persist_runtime_state(halted=self.halted, entries_enabled=self.entries_enabled)
            await self._transition(status, "COMPLETED", event_type="command.completed"); return
        if kind in {"position.closeAll", "order.cancelAll"}:
            await self._bulk(status, kind, origin); return
        if kind not in MUTATION_KINDS:
            await self._transition(status, "FAILED", reason="UNSUPPORTED_COMMAND", event_type="command.failed"); return
        if internal_record is not None:
            await self._execute_internal(internal_record, kind, payload, scope)
        else:
            await self._execute(status, kind, payload, scope, origin)

    def _scope(self, kind: str, request: CommandRequest | InternalEntryRequest, status: RuntimeCommandStatus | InternalCommandRecord) -> str:
        if kind == "INTERNAL_ENTRY_MARKET": return f"entry:{request.symbol}"
        if kind.startswith("runtime."): return "runtime"
        return f"{kind}:{status.target_id or 'all'}"

    async def _execute_internal(self, record: InternalCommandRecord, kind: str, payload: dict[str, Any], scope: str) -> None:
        self._locks.add(scope)
        if kind == "INTERNAL_ENTRY_MARKET": self._pending.register_entry(str(payload["symbol"]), record.command_id)
        record = await self._transition_internal(record, "ACCEPTED", event_type="command.accepted")
        record = await self._transition_internal(record, "IN_PROGRESS", event_type="command.progress")
        target = record.target_id
        future = self._gateway.mutation(record.command_id, kind, target, payload, reason="KILL_SWITCH" if self.halted else "MANUAL")
        try: result = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=self._risk_config.gateway_timeout_s)
        except asyncio.TimeoutError:
            await self._unknown_internal(record, kind, scope, target, "OUTCOME_AMBIGUOUS"); return
        except Exception:
            await self._unknown_internal(record, kind, scope, target, "BROKER_DISCONNECT_MID_CALL"); return
        if getattr(result, "retcode", None) in self._gateway.success_retcodes():
            await self._transition_internal(record, "COMPLETED", event_type="command.completed")
        elif getattr(result, "retcode", None) is not None:
            await self._transition_internal(record, "FAILED", reason="ORDER_CHECK_REJECTED" if getattr(result, "_order_check", False) else "BROKER_REJECTED", event_type="command.failed")
        else: await self._unknown_internal(record, kind, scope, target, "OUTCOME_AMBIGUOUS"); return
        self._release(scope, target, payload)

    async def _unknown_internal(self, record: InternalCommandRecord, kind: str, scope: str, target: str | None, reason: str) -> None:
        await self._transition_internal(record, "EXECUTION_UNKNOWN", reason=reason, event_type="command.execution_unknown")
        await self._bus.publish(self._envelope(record, "reconciliation.issue.detected", "EXECUTION_UNKNOWN", reason, {"targetScope": scope}), mutates_state=False)
        if target and target.isdigit(): self._pending.retain_for_reconciliation(int(target))
        try:
            result = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(self._gateway.verify(target))), timeout=self._risk_config.verification_timeout_s)
            executed, vreason = verdict(kind, result)
            if executed is True:
                await self._bus.publish(self._envelope(record, "reconciliation.issue.resolved", "COMPLETED", None, {"targetScope": scope, "verdict": "executed"}), mutates_state=False)
                await self._transition_internal(record, "COMPLETED", event_type="command.completed")
                self._release(scope, target, {})
            elif executed is False:
                await self._transition_internal(record, "FAILED", reason=vreason or "BROKER_REJECTED", event_type="command.failed")
                self._release(scope, target, {})
            # else: verdict=None → stay EXECUTION_UNKNOWN (ambiguous, not resolved)
        except asyncio.TimeoutError:
            await self._verification_unresolved_internal(record, scope, target)

    async def _execute(self, status: RuntimeCommandStatus, kind: str, payload: dict[str, Any], scope: str, origin: str = "TRANSPORT") -> None:
        self._locks.add(scope)
        target = status.target_id
        if kind == "INTERNAL_ENTRY_MARKET": self._pending.register_entry(str(payload["symbol"]), status.command_id)
        elif target and target.isdigit():
            ticket = int(target)
            if kind == "position.close":
                er = "KILL_SWITCH" if self.halted else "MANUAL"
                self._pending.register_close(ticket, status.command_id, exit_reason=er, correlation_id=status.correlation_id)
            elif kind == "position.closePartial": self._pending.register_partial(ticket, float(payload.get("volume", 0)), status.command_id)
            elif kind == "position.modifyProtection": self._pending.register_modify(ticket, status.command_id)
        accepted = await self._transition(status, "ACCEPTED", event_type="command.accepted")
        progress = await self._transition(accepted, "IN_PROGRESS", event_type="command.progress")
        future = self._gateway.mutation(progress.command_id, kind, target, payload, reason="KILL_SWITCH" if self.halted else "MANUAL")
        try: result = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=self._risk_config.gateway_timeout_s)
        except asyncio.TimeoutError:
            await self._unknown(progress, kind, scope, target, "OUTCOME_AMBIGUOUS"); return
        except Exception:
            await self._unknown(progress, kind, scope, target, "BROKER_DISCONNECT_MID_CALL"); return
        if getattr(result, "retcode", None) in self._gateway.success_retcodes():
            await self._transition(progress, "COMPLETED", event_type="command.completed")
        elif getattr(result, "retcode", None) is not None:
            await self._transition(progress, "FAILED", reason="ORDER_CHECK_REJECTED" if getattr(result, "_order_check", False) else "BROKER_REJECTED", event_type="command.failed")
        else: await self._unknown(progress, kind, scope, target, "OUTCOME_AMBIGUOUS"); return
        self._release(scope, target, payload)

    async def _execute_child(self, child_status: RuntimeCommandStatus, kind: str, payload: dict[str, Any], scope: str, origin: str = "TRANSPORT") -> str:
        """Execute a child bulk operation. Returns outcome: 'successful', 'failed', or 'unknown'.
        Does NOT transition the parent command — only the child status.
        """
        target = child_status.target_id
        self._locks.add(scope)
        if target and target.isdigit():
            ticket = int(target)
            if kind == "position.close":
                self._pending.register_close(ticket, child_status.command_id, exit_reason="KILL_SWITCH" if self.halted else "MANUAL", correlation_id=child_status.correlation_id)
            elif kind == "order.cancel":
                pass
        accepted = await self._transition(child_status, "ACCEPTED", event_type="command.accepted")
        progress = await self._transition(accepted, "IN_PROGRESS", event_type="command.progress")
        future = self._gateway.mutation(progress.command_id, kind, target, payload, reason="KILL_SWITCH" if self.halted else "MANUAL")
        try:
            result = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=self._risk_config.gateway_timeout_s)
        except asyncio.TimeoutError:
            await self._transition(child_status, "EXECUTION_UNKNOWN", reason="OUTCOME_AMBIGUOUS", event_type="command.execution_unknown")
            # Keep lock for unknown — parent scope retained
            return "unknown"
        except Exception:
            await self._transition(child_status, "EXECUTION_UNKNOWN", reason="BROKER_DISCONNECT_MID_CALL", event_type="command.execution_unknown")
            return "unknown"
        if getattr(result, "retcode", None) in self._gateway.success_retcodes():
            await self._transition(child_status, "COMPLETED", event_type="command.completed")
            self._release(scope, target, payload)
            return "successful"
        elif getattr(result, "retcode", None) is not None:
            reason = "ORDER_CHECK_REJECTED" if getattr(result, "_order_check", False) else "BROKER_REJECTED"
            await self._transition(child_status, "FAILED", reason=reason, event_type="command.failed")
            self._release(scope, target, payload)
            return "failed"
        else:
            await self._transition(child_status, "EXECUTION_UNKNOWN", reason="OUTCOME_AMBIGUOUS", event_type="command.execution_unknown")
            return "unknown"

    async def _unknown(self, status: RuntimeCommandStatus, kind: str, scope: str, target: str | None, reason: str) -> None:
        await self._transition(status, "EXECUTION_UNKNOWN", reason=reason, event_type="command.execution_unknown")
        await self._bus.publish(self._envelope(status, "reconciliation.issue.detected", "EXECUTION_UNKNOWN", reason, {"targetScope": scope}), mutates_state=False)
        if target and target.isdigit(): self._pending.retain_for_reconciliation(int(target))
        try:
            result = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(self._gateway.verify(target))), timeout=self._risk_config.verification_timeout_s)
            executed, vreason = verdict(kind, result)
            if executed is True:
                await self._bus.publish(self._envelope(status, "reconciliation.issue.resolved", "COMPLETED", None, {"targetScope": scope, "verdict": "executed"}), mutates_state=False)
                await self._transition(status, "COMPLETED", event_type="command.completed")
                self._release(scope, target, {})
            elif executed is False:
                await self._transition(status, "FAILED", reason=vreason or "BROKER_REJECTED", event_type="command.failed")
                self._release(scope, target, {})
            # else: verdict=None → stay EXECUTION_UNKNOWN (ambiguous, not resolved)
        except asyncio.TimeoutError:
            await self._verification_unresolved(status, scope, target)

    def _release(self, scope: str, target: str | None, payload: dict[str, Any]) -> None:
        self._locks.discard(scope)
        if target and target.isdigit(): self._pending.clear(int(target))
        if "symbol" in payload: self._pending.clear_entry(str(payload["symbol"]))
        self._facts.unlock_entity(scope)

    async def _verification_unresolved(self, status: RuntimeCommandStatus, scope: str, target: str | None) -> None:
        alert_payload = {"commandId": status.command_id, "targetScope": scope, "reason": "OUTCOME_AMBIGUOUS"}
        await self._bus.publish(
            RuntimeEventEnvelope(event_id=str(uuid.uuid4()), type="alert.created", runtime_id=self._runtime_id,
                                 boot_id=self._bus.boot_id, sequence=0, revision=0, occurred_at=_now(),
                                 emitted_at=_now(), received_at=_now(), severity="CRITICAL",
                                 source="LOCAL_RUNTIME", correlation_id=status.correlation_id,
                                 command_id=status.command_id, payload=alert_payload),
            mutates_state=False,
        )

    async def _verification_unresolved_internal(self, record: InternalCommandRecord, scope: str, target: str | None) -> None:
        alert_payload = {"commandId": record.command_id, "targetScope": scope, "reason": "OUTCOME_AMBIGUOUS"}
        await self._bus.publish(
            RuntimeEventEnvelope(event_id=str(uuid.uuid4()), type="alert.created", runtime_id=self._runtime_id,
                                 boot_id=self._bus.boot_id, sequence=0, revision=0, occurred_at=_now(),
                                 emitted_at=_now(), received_at=_now(), severity="CRITICAL",
                                 source="LOCAL_RUNTIME", correlation_id=record.correlation_id,
                                 command_id=record.command_id, payload=alert_payload),
            mutates_state=False,
        )

    async def _bulk(self, status: RuntimeCommandStatus, kind: str, origin: str = "TRANSPORT") -> None:
        counts = {"successful": 0, "failed": 0, "unknown": 0, "skipped": 0, "remaining": 0, "foreignObserved": 0}
        straggler_ids: list[str] = []
        child_statuses: list[RuntimeCommandStatus] = []

        sweep = await asyncio.wrap_future(self._gateway.sweep_facts())
        if kind == "order.cancelAll":
            items = sweep.get("orders", ()) if isinstance(sweep, dict) else ()
            child_kind = "order.cancel"
            child_scope_fmt = "order.cancel:{}"
        else:
            items = sweep.get("positions", ()) if isinstance(sweep, dict) else ()
            child_kind = "position.close"
            child_scope_fmt = "position.close:{}"

        for item in items:
            if item.get("magic") != self._bot_magic:
                counts["foreignObserved"] += 1
                continue
            ticket = item["ticket"]
            now = _now()
            child_id = str(uuid.uuid4())
            child_status = RuntimeCommandStatus(
                command_id=child_id,
                client_request_id=str(uuid.uuid4()),
                correlation_id=status.correlation_id,
                idempotency_key=f"{status.idempotency_key}/child/{kind}/{ticket}",
                kind=child_kind,
                target_id=str(ticket),
                state="PREPARED",
                created_at=now,
                updated_at=now,
            )
            child_envelope = self._envelope(child_status, "command.created", "PREPARED", None, {"kind": child_kind, "parentId": status.command_id})
            saved, created = await self._bus.publish_command_created(
                child_envelope, child_status, '{"kind":"child"}', origin="TRANSPORT",
            )
            if not created:
                # Idempotency collision — should not happen with unique child IDs
                counts["skipped"] += 1
                continue
            child_statuses.append(saved)

        # Process each child, collecting outcomes. Continue after any failure/unknown.
        for cs in child_statuses:
            ticket = cs.target_id
            scope = child_scope_fmt.format(ticket)
            outcome = await self._execute_child(cs, child_kind, {}, scope, origin)
            counts[outcome] += 1

        # Rescan for stragglers (orders/positions that remain despite successful individual closes)
        rescan = await asyncio.wrap_future(self._gateway.sweep_facts())
        if kind == "order.cancelAll":
            remaining = rescan.get("orders", ()) if isinstance(rescan, dict) else ()
        else:
            remaining = rescan.get("positions", ()) if isinstance(rescan, dict) else ()
        for item in remaining:
            if item.get("magic") == self._bot_magic:
                straggler_ids.append(str(item["ticket"]))
        counts["remaining"] = len(straggler_ids)

        payload = {
            "counts": counts,
            "stragglerIds": straggler_ids,
        }

        if straggler_ids or counts.get("failed", 0) > 0 or counts.get("unknown", 0) > 0:
            await self._transition(status, "FAILED", event_type="command.failed", extra=payload)
            alert = RuntimeEventEnvelope(
                event_id=str(uuid.uuid4()), type="alert.created",
                runtime_id=self._runtime_id, boot_id=self._bus.boot_id,
                sequence=0, revision=0, occurred_at=_now(), emitted_at=_now(),
                received_at=_now(), severity="CRITICAL",
                source="LOCAL_RUNTIME", command_id=status.command_id,
                payload={"commandId": status.command_id, "reason": "BULK_FAILED", "kind": kind, "counts": counts, "stragglerIds": straggler_ids},
            )
            await self._bus.publish(alert, mutates_state=False)
        else:
            await self._transition(status, "COMPLETED", event_type="command.completed", extra=payload)

    async def _bulk_child_ops(self, status: RuntimeCommandStatus, kind: str, origin: str) -> dict[str, Any]:
        """Run bulk child operations without transitioning parent terminal.
        Returns counts dict. Used by _emergency to avoid double terminal transitions.
        """
        counts = {"successful": 0, "failed": 0, "unknown": 0, "skipped": 0, "foreignObserved": 0}

        sweep = await asyncio.wrap_future(self._gateway.sweep_facts())
        if kind == "order.cancelAll":
            items = sweep.get("orders", ()) if isinstance(sweep, dict) else ()
            child_kind = "order.cancel"
            child_scope_fmt = "order.cancel:{}"
        else:
            items = sweep.get("positions", ()) if isinstance(sweep, dict) else ()
            child_kind = "position.close"
            child_scope_fmt = "position.close:{}"

        child_statuses: list[RuntimeCommandStatus] = []
        for item in items:
            if item.get("magic") != self._bot_magic:
                counts["foreignObserved"] += 1
                continue
            ticket = item["ticket"]
            now = _now()
            child_id = str(uuid.uuid4())
            child_status = RuntimeCommandStatus(
                command_id=child_id,
                client_request_id=str(uuid.uuid4()),
                correlation_id=status.correlation_id,
                idempotency_key=f"{status.idempotency_key}/child/{kind}/{ticket}",
                kind=child_kind,
                target_id=str(ticket),
                state="PREPARED",
                created_at=now,
                updated_at=now,
            )
            child_envelope = self._envelope(child_status, "command.created", "PREPARED", None, {"kind": child_kind, "parentId": status.command_id})
            saved, created = await self._bus.publish_command_created(
                child_envelope, child_status, '{"kind":"child"}', origin="TRANSPORT",
            )
            if not created:
                counts["skipped"] += 1
                continue
            child_statuses.append(saved)

        for cs in child_statuses:
            ticket = cs.target_id
            scope = child_scope_fmt.format(ticket)
            outcome = await self._execute_child(cs, child_kind, {}, scope, origin)
            counts[outcome] += 1

        return {"counts": counts, "child_kind": child_kind}

    async def _emergency(self, status: RuntimeCommandStatus, origin: str = "TRANSPORT") -> None:
        # Halt BEFORE any I/O
        self.halted, self.entries_enabled = True, False
        self._persist_runtime_state(halted=True, entries_enabled=False)
        await self._emit_safety("safety.kill.started", status, "INFO")
        # Cancel orders first (no parent terminal transition)
        order_result = await self._bulk_child_ops(status, "order.cancelAll", origin)
        order_counts = order_result["counts"]
        await self._emit_safety("safety.kill.progress", status, "INFO", extra={"phase": "ordersCancelled", "counts": order_counts})
        # Close positions second (no parent terminal transition)
        pos_result = await self._bulk_child_ops(status, "position.closeAll", origin)
        pos_counts = pos_result["counts"]
        await self._emit_safety("safety.kill.progress", status, "INFO", extra={"phase": "positionsClosed", "counts": pos_counts})
        # Rescan for stragglers
        remaining = await asyncio.wrap_future(self._gateway.sweep_facts())
        stragglers: list[str] = []
        for o in (remaining.get("orders", ()) if isinstance(remaining, dict) else ()):
            if o.get("magic") == self._bot_magic:
                stragglers.append(f"order:{o.get('ticket')}")
        for p in (remaining.get("positions", ()) if isinstance(remaining, dict) else ()):
            if p.get("magic") == self._bot_magic:
                stragglers.append(f"position:{p.get('ticket')}")
        total_counts = {
            "successful": order_counts.get("successful", 0) + pos_counts.get("successful", 0),
            "failed": order_counts.get("failed", 0) + pos_counts.get("failed", 0),
            "unknown": order_counts.get("unknown", 0) + pos_counts.get("unknown", 0),
            "skipped": order_counts.get("skipped", 0) + pos_counts.get("skipped", 0),
            "remaining": len(stragglers),
            "foreignObserved": order_counts.get("foreignObserved", 0) + pos_counts.get("foreignObserved", 0),
        }
        payload = {
            "counts": total_counts,
            "stragglerIds": stragglers,
        }
        if stragglers:
            await self._transition(status, "FAILED", event_type="command.failed", extra=payload)
            await self._emit_safety("safety.kill.failed", status, "CRITICAL", extra={"stragglerIds": stragglers})
            alert = RuntimeEventEnvelope(
                event_id=str(uuid.uuid4()), type="alert.created",
                runtime_id=self._runtime_id, boot_id=self._bus.boot_id,
                sequence=0, revision=0, occurred_at=_now(), emitted_at=_now(),
                received_at=_now(), severity="CRITICAL",
                source="LOCAL_RUNTIME", command_id=status.command_id,
                payload={"commandId": status.command_id, "reason": "EMERGENCY_STRAAGGLERS", "stragglerIds": stragglers},
            )
            await self._bus.publish(alert, mutates_state=False)
        else:
            await self._transition(status, "COMPLETED", event_type="command.completed", extra=payload)
            await self._emit_safety("safety.kill.completed", status, "INFO")

    async def _emit_safety(self, event_type: str, status: RuntimeCommandStatus, severity: str, extra: dict[str, Any] | None = None) -> None:
        envelope = self._envelope(status, event_type, "IN_PROGRESS", None, extra)
        await self._bus.publish(envelope.model_copy(update={"severity": severity}), mutates_state=False)
