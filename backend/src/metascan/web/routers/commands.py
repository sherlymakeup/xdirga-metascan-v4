from __future__ import annotations

# POST /v4/commands        — §10.4  submit command (idempotent)
# GET  /v4/commands/{commandId} — §10.1  poll single command status
#
# Idempotency: identical idempotencyKey within retention window returns the
# SAME commandId and current state — no new command created.
# SP5: command starts as PREPARED, emits command.created, enqueues to pipeline.
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
from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.models import RuntimeCommandStatus, RuntimeEventEnvelope
from metascan.journal.commands import IdempotencyConflict
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.command_queue import CommandQueueFull
from metascan.pipeline.request import CommandRequest as PipelineCommandRequest
from metascan.web.dependencies import get_bus, get_journal, get_pipeline
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
    pipeline: CommandPipeline = Depends(get_pipeline),
    _token: str = Depends(verify_token),
) -> dict:
    try:
        request = PipelineCommandRequest.from_ingress(payload.model_dump(by_alias=True, exclude_none=True))
        if request.kind not in RUNTIME_COMMAND_KINDS:
            raise HTTPException(status_code=422, detail={"error": "Unknown command kind", "code": "VALIDATION_FAILED"})
        status = await pipeline.submit_transport(request, idempotency_key=payload.idempotencyKey, correlation_id=payload.correlationId)
    except IdempotencyConflict:
        raise HTTPException(status_code=409, detail={"error": "idempotency key reused with different request", "code": "IDEMPOTENCY_CONFLICT"}) from None
    except CommandQueueFull:
        raise HTTPException(status_code=503, detail={"error": "Command queue full", "code": "QUEUE_FULL"}) from None
    state = status.state.value if hasattr(status.state, "value") else str(status.state)
    return {"commandId": status.command_id, "state": state, "receivedAt": status.created_at, "idempotencyKey": payload.idempotencyKey}


@router.get("/commands/{command_id}")
async def get_command(
    command_id: str,
    journal: Journal = Depends(get_journal),
    _token: str = Depends(verify_token),
) -> dict:
    def _fetch(conn):
        row = conn.execute(
            "SELECT record_json FROM commands WHERE command_id = ? AND origin = 'TRANSPORT'",
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
