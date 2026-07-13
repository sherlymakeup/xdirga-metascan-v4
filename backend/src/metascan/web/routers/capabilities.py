from __future__ import annotations

# GET /v4/capabilities — §10.1
# Returns RuntimeCapabilities: allowed commands + feature flags.
# Contract source: HANDOFF.md §10.1, runtime-types.ts RuntimeCapabilities.

import datetime

from fastapi import APIRouter, Depends

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.web.dependencies import get_bus, get_config
from metascan.web.security import verify_token

router = APIRouter()

_SAFETY_CRITICAL = frozenset({
    "runtime.emergencyKill",
    "runtime.pause",
    "runtime.disableEntries",
    "order.cancelAll",
    "position.closeAll",
})

_RISK_LEVEL: dict[str, int] = {
    "runtime.emergencyKill": 4,
    "runtime.pause": 3,
    "runtime.disableEntries": 3,
    "order.cancelAll": 3,
    "position.closeAll": 3,
    "position.close": 2,
    "order.cancel": 2,
    "position.management.pause": 2,
    "position.management.resume": 2,
    "config.apply": 2,
    "config.rollback": 2,
}


def _build_command_capability(kind: str) -> dict:
    risk = _RISK_LEVEL.get(kind, 1)
    safety = kind in _SAFETY_CRITICAL
    return {
        "command": kind,
        "allowed": True,
        "riskLevel": risk,
        "requiresReason": safety,
        "requiresTypedConfirmation": risk >= 3,
    }


@router.get("/capabilities")
async def get_capabilities(
    bus: EventBus = Depends(get_bus),
    _token: str = Depends(verify_token),
) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    commands = {kind: _build_command_capability(kind) for kind in RUNTIME_COMMAND_KINDS}
    return {
        "revision": bus.revision,
        "generatedAt": now,
        "source": "LOCAL_RUNTIME",
        "commands": commands,
    }
