from __future__ import annotations

# GET /v4/health — §10.7
# GET /v4/ops/metrics — SP4_DESIGN §2.2

import time

from fastapi import APIRouter, Depends

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.web.dependencies import get_bus, get_journal
from metascan.web.sse import active_sse_connections

router = APIRouter()

_START_TIME = time.monotonic()


@router.get("/health")
async def get_health(
    journal: Journal = Depends(get_journal),
) -> dict:
    db_ok = journal.is_open
    return {
        "status": "OK" if db_ok else "DEGRADED",
        "mt5_connected": False,
        "db_ok": db_ok,
        "uptime": time.monotonic() - _START_TIME,
    }


@router.get("/ops/metrics")
async def get_metrics(
    bus: EventBus = Depends(get_bus),
) -> dict:
    return {
        "eventBusQueueSize": sum(
            s._queue_ref().qsize() for s in bus._subs.values()
        ),
        "mt5PollLatencyMs": 0.0,
        "sqliteCommitLatencyMs": 0.0,
        # Real counter incremented/decremented by SseHandoff.generate_stream
        "activeSseConnections": active_sse_connections.count,
    }
