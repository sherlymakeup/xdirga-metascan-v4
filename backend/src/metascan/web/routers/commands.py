from __future__ import annotations

# POST /v4/commands        — §10.4  submit command (idempotent)
# GET  /v4/commands/{commandId} — §10.1  poll single command status
#
# Idempotency: identical idempotencyKey within retention window returns the
# SAME commandId and current state — no new command created.
# SP4 constraint: no MT5 execution occurs here.
#
# Transition sequence fix: the CommandTransitionRecord.sequence MUST equal the
# stamped event sequence. Both are assigned inside EventBus._publish_lock by
# publish_command_event, which stamps the envelope first and then builds the
# transition from stamped.sequence. Callers must NOT pre-build a transition
# with bus.sequence (pre-stamp) — that would commit a wrong sequence to the DB.
# Contract source: HANDOFF.md §10.4, runtime-types.ts CommandAccepted/RuntimeCommandStatus.

import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from metascan.bus.event_bus import EventBus
from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.journal.commands import get_command_by_idempotency_key
from metascan.journal.db import Journal
from metascan.web.dependencies import get_bus, get_journal
from metascan.web.security import verify_token

router = APIRouter()


class CommandRequest(BaseModel):
    kind: str
    params: dict[str, Any] | None = None
    idempotencyKey: str
    correlationId: str | None = None
    operatorId: str | None = None
    clientRequestId: str | None = None
    targetId: str | None = None
    expectedRevision: int | None = None
    reason: str | None = None
    parameters: dict[str, Any] | None = None
    submittedAt: str | None = None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/commands")
async def submit_command(
    payload: CommandRequest,
    journal: Journal = Depends(get_journal),
    bus: EventBus = Depends(get_bus),
    _token: str = Depends(verify_token),
) -> dict:
    now = _now()
    correlation_id = payload.correlationId or str(uuid.uuid4())
    client_request_id = payload.clientRequestId or str(uuid.uuid4())

    # Idempotency check — read-only under writer thread, no stamp yet
    existing = journal.run_on_writer(
        lambda conn: get_command_by_idempotency_key(conn, payload.idempotencyKey)
    )
    if existing is not None:
        state_str = existing.state.value if hasattr(existing.state, "value") else str(existing.state)
        return {
            "commandId": existing.command_id,
            "state": state_str,
            "receivedAt": existing.created_at,
            "idempotencyKey": payload.idempotencyKey,
        }

    command_id = str(uuid.uuid4())

    status = RuntimeCommandStatus(
        command_id=command_id,
        client_request_id=client_request_id,
        correlation_id=correlation_id,
        idempotency_key=payload.idempotencyKey,
        kind=payload.kind,
        target_id=payload.targetId,
        state="ACCEPTED",
        created_at=now,
        updated_at=now,
    )

    # Envelope sequence/revision are pre-stamp placeholders; publish_command_event
    # stamps the real values inside _publish_lock before committing to DB.
    # DO NOT pre-build CommandTransitionRecord here — publish_command_event builds
    # it from stamped.sequence inside the lock, ensuring transition.sequence ==
    # event.sequence in the journal (item 4 invariant).
    envelope = RuntimeEventEnvelope(
        event_id=str(uuid.uuid4()),
        type="command.accepted",
        runtime_id="xdirga",
        boot_id=bus.boot_id,
        sequence=0,   # placeholder — overwritten by _stamp inside lock
        revision=0,   # placeholder — overwritten by _stamp inside lock
        occurred_at=now,
        emitted_at=now,
        received_at=now,
        severity="INFO",
        source="LOCAL_RUNTIME",
        correlation_id=correlation_id,
        command_id=command_id,
        payload={"commandId": command_id, "state": "ACCEPTED"},
    )

    # publish_command_event: under _publish_lock stamps envelope, builds
    # transition from stamped.sequence, commits bundle atomically, then fanouts.
    # This is the only path that writes to DB — no prior commit exists.
    await bus.publish_command_event(
        envelope, status, from_state=None, mutates_state=False
    )

    return {
        "commandId": command_id,
        "state": "ACCEPTED",
        "receivedAt": now,
        "idempotencyKey": payload.idempotencyKey,
    }


@router.get("/commands/{command_id}")
async def get_command(
    command_id: str,
    journal: Journal = Depends(get_journal),
    _token: str = Depends(verify_token),
) -> dict:
    def _fetch(conn):
        row = conn.execute(
            "SELECT record_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return RuntimeCommandStatus.model_validate_json(row[0])

    status = journal.run_on_writer(_fetch)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Command not found", "code": "NOT_FOUND"},
        )

    state_str = status.state.value if hasattr(status.state, "value") else str(status.state)
    kind_str = status.kind.value if hasattr(status.kind, "value") else str(status.kind)
    return {
        "commandId": status.command_id,
        "clientRequestId": status.client_request_id,
        "correlationId": status.correlation_id,
        "idempotencyKey": status.idempotency_key,
        "kind": kind_str,
        "targetId": status.target_id,
        "state": state_str,
        "progress": status.progress,
        "currentStep": status.current_step,
        "message": status.message,
        "errorCode": status.error_code,
        "reason": status.reason,
        "createdAt": status.created_at,
        "updatedAt": status.updated_at,
        "completedAt": status.completed_at,
    }
