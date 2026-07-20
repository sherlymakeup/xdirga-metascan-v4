from __future__ import annotations

# GET /v4/health — §10.7
# GET /v4/ops/metrics — SP4_DESIGN §2.2

import time

from fastapi import APIRouter, Depends, Request

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.web.dependencies import get_bus, get_journal, get_pipeline
from metascan.web.sse import active_sse_connections

router = APIRouter()

_START_TIME = time.monotonic()


@router.get("/health")
async def get_health(
    request: Request,
    journal: Journal = Depends(get_journal),
) -> dict:
    db_ok = journal.is_open
    # status = API process / journal; mt5_connected = broker readiness (separate field)
    mt5_connected = False
    consumer = getattr(request.app.state, "consumer", None)
    if consumer is not None:
        mt5_connected = getattr(consumer, "connection_state", "") == "CONNECTED"
    return {
        "status": "OK" if db_ok else "DEGRADED",
        "mt5_connected": mt5_connected,
        "db_ok": db_ok,
        "uptime": time.monotonic() - _START_TIME,
    }


@router.get("/ops/metrics")
async def get_metrics(
    request: Request,
    bus: EventBus = Depends(get_bus),
    pipeline=Depends(get_pipeline),
) -> dict:
    metrics = getattr(request.app.state, "metrics", None)
    poll_latency = metrics.cycle_p50() if metrics is not None else None
    return {
        "eventBusQueueSize": sum(
            s._queue_ref().qsize() for s in bus._subs.values()
        ),
        "mt5PollLatencyMs": poll_latency if poll_latency is not None else 0.0,
        "sqliteCommitLatencyMs": 0.0,
        "mutationInFlight": pipeline.mutation_in_flight,
        "activeSseConnections": active_sse_connections.count,
    }
