from __future__ import annotations

# GET /v4/events/stream — §10.5
# SSE event stream. Auth via ?token= query param (EventSource cannot set headers).
# bootId MUST be provided; BOOT_ID_UNKNOWN accepted only with sequence=0.
# Each frame: id=sequence, event=type, data=JSON envelope.
# Reconnect: Last-Event-ID header → resume from sequence+1 or emit system.resync.required.
# Control frames stay open per §3.3 — connection is NOT closed on resync.
# Contract source: HANDOFF.md §10.5, SP4_DESIGN §3.

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.web.dependencies import get_bus, get_journal
from metascan.web.security import verify_token
from metascan.web.sse import SseHandoff

router = APIRouter()


@router.get("/events/stream")
async def get_stream(
    request: Request,
    boot_id: str = Query(..., alias="bootId"),
    sequence: int = Query(0),
    bus: EventBus = Depends(get_bus),
    journal: Journal = Depends(get_journal),
    _token: str = Depends(verify_token),
) -> StreamingResponse:
    # bootId mismatch against current backend bootId → reject per §3.1
    if boot_id != "BOOT_ID_UNKNOWN" and boot_id != bus.boot_id:
        raise HTTPException(status_code=400, detail="BOOT_MISMATCH")

    # Last-Event-ID header takes precedence over sequence query param
    last_event_id_hdr = request.headers.get("last-event-id")
    snapshot_sequence = sequence
    if last_event_id_hdr is not None:
        try:
            snapshot_sequence = int(last_event_id_hdr)
        except ValueError:
            pass

    subscriber_id = str(uuid.uuid4())
    handoff = SseHandoff(bus, journal)

    return StreamingResponse(
        handoff.generate_stream(subscriber_id, boot_id, snapshot_sequence),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
