from __future__ import annotations

# GET /v4/snapshot — §10.3
# Returns RuntimeSnapshotEnvelope { metadata, snapshot: CockpitSnapshot }.
# Snapshot is atomic; partial snapshots are forbidden.
# The sequence captured here is the handoff boundary for race-free SSE splice.
# Contract source: HANDOFF.md §10.3, runtime-types.ts RuntimeSnapshotEnvelope.

import datetime

from fastapi import APIRouter, Depends

from metascan.bus.event_bus import EventBus
from metascan.contract.hash import GOLDEN_SCHEMA_HASH
from metascan.web.dependencies import get_bus
from metascan.web.security import verify_token

router = APIRouter()

_RUNTIME_ID = "xdirga"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_snapshot() -> dict:
    """Minimal valid CockpitSnapshot for SP4 (no MT5 execution)."""
    now = _now_iso()
    return {
        "runtime": {
            "id": _RUNTIME_ID,
            "sessionId": "session-sp4",
            "version": "4.1.0",
            "buildHash": "dev",
            "environment": "LOCAL",
            "tradingMode": "TRIAL",
            "state": "READY",
            "previousState": "INITIALIZING",
            "stateChangedAt": now,
            "stateReason": "SP4_NO_MT5",
            "startedAt": now,
            "uptimeSec": 0,
            "lastHeartbeatAt": now,
            "heartbeatLatencyMs": 0.0,
            "entriesEnabled": False,
            "automationEnabled": False,
            "hostname": "localhost",
            "os": "win32",
            "pid": 0,
        },
        "subsystems": [],
        "broker": {
            "broker": "EXNESS",
            "server": "",
            "loginMasked": "***",
            "accountMode": "TRIAL",
            "connection": "DISCONNECTED",
            "tradingPermitted": False,
            "terminalVersion": "",
            "lastTickAt": now,
            "lastRequestAt": now,
            "queueDepth": 0,
            "avgLatencyMs": 0.0,
            "timeoutCount": 0,
            "reconnectAttempts": 0,
        },
        "account": {
            "currency": "USD",
            "balance": 0.0,
            "equity": 0.0,
            "margin": 0.0,
            "freeMargin": 0.0,
            "marginLevel": 0.0,
            "floatingPnl": 0.0,
            "realizedPnlToday": 0.0,
            "realizedPnlWeek": 0.0,
            "dailyDrawdown": 0.0,
            "maxDrawdown": 0.0,
            "grossExposure": 0.0,
            "netExposure": 0.0,
            "openPositions": 0,
            "pendingOrders": 0,
            "tradesToday": 0,
            "winRate": 0.0,
            "profitFactor": 0.0,
            "riskUtilization": 0.0,
            "updatedAt": now,
            "freshness": "UNAVAILABLE",
        },
        "strategies": [],
        "positions": [],
        "orders": [],
        "markets": [],
        "alerts": [],
        "incidents": [],
        "riskLimits": [],
        "breakers": [],
        "reconciliation": {
            "state": "IDLE",
            "lastRunAt": now,
            "brokerOrders": 0,
            "runtimeOrders": 0,
            "brokerPositions": 0,
            "runtimePositions": 0,
            "missingOrders": 0,
            "unknownOrders": 0,
            "positionMismatches": 0,
            "volumeMismatches": 0,
            "stateMismatches": 0,
            "issues": [],
        },
        "events": [],
        "equityCurve": [],
    }


@router.get("/snapshot")
async def get_snapshot(
    bus: EventBus = Depends(get_bus),
    _token: str = Depends(verify_token),
) -> dict:
    now = _now_iso()
    return {
        "metadata": {
            "runtimeId": _RUNTIME_ID,
            "bootId": bus.boot_id,
            "revision": bus.revision,
            "sequence": bus.sequence,
            "generatedAt": now,
            "serverTimestamp": now,
            "protocolId": "xdirga-runtime-v4",
            "protocolVersion": "4.1.0",
            "schemaVersion": "1.1.0",
            "schemaHash": GOLDEN_SCHEMA_HASH,
            "source": "LOCAL_RUNTIME",
        },
        "snapshot": _empty_snapshot(),
    }
