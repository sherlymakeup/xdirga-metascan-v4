from __future__ import annotations

# GET /v4/handshake — §10.2
# Returns RuntimeHandshake matching runtime-types.ts RuntimeHandshake interface.
# Contract source: HANDOFF.md §10.2, runtime-contract.ts EXPECTED_RUNTIME_CONTRACT.

import datetime
import uuid

from fastapi import APIRouter, Depends

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.hash import GOLDEN_SCHEMA_HASH, PROTOCOL_VERSION, SCHEMA_VERSION
from metascan.web.dependencies import get_bus, get_config
from metascan.web.security import verify_token

router = APIRouter()

_SUPPORTED_FEATURES = [
    "runtime.capabilities",
    "runtime.commands",
    "runtime.events",
    "runtime.reconciliation",
    "runtime.safety",
    "position.management",
    "trade.history",
]

_RUNTIME_ID = "xdirga"


@router.get("/handshake")
async def get_handshake(
    config: AppConfig = Depends(get_config),
    bus: EventBus = Depends(get_bus),
    _token: str = Depends(verify_token),
) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "runtimeName": config.runtime.runtime_name,
        "runtimeVersion": PROTOCOL_VERSION,
        "runtimeId": _RUNTIME_ID,
        "bootId": bus.boot_id,
        "protocolId": config.runtime.protocol_id,
        "protocolVersion": config.runtime.protocol_version,
        "schemaVersion": config.runtime.schema_version,
        "schemaHash": GOLDEN_SCHEMA_HASH,
        "capabilitiesRevision": 1,
        "minFrontendVersion": "1.0.0",
        "frontendVersion": "1.1.0",
        "supportedFeatures": _SUPPORTED_FEATURES,
        "supportedCommands": list(RUNTIME_COMMAND_KINDS),
        "brokerProvider": config.runtime.broker_provider,
        "brokerEnvironment": config.runtime.broker_environment,
        "executionSemantics": config.runtime.execution_semantics,
        "source": "LOCAL_RUNTIME",
        "observedAt": now,
    }
