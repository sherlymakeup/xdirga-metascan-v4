"""Deterministic canonical sorted compact JSON SHA-256 over full contract schema."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.enums import MANAGEMENT_ACTIONS, TRADE_EXIT_REASONS
from metascan.contract.events import RUNTIME_EVENT_TYPES
from metascan.contract.models import ContractCatalog

PROTOCOL_VERSION = "4.1.0"
SCHEMA_VERSION = "1.1.0"

# Pinned literal — recompute with `python -m metascan.contract hash` after schema changes.
GOLDEN_SCHEMA_HASH = "2e93c9ef25a88061c9b43b1a67b2eb3f95b2dc03612731d96d14ddccc97895f4"

# Non-semantic JSON Schema noise stripped for cross-version stability.
_STRIP_KEYS = frozenset({"title", "description"})


def _strip_noise(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_noise(v)
            for k, v in obj.items()
            if k not in _STRIP_KEYS
        }
    if isinstance(obj, list):
        return [_strip_noise(v) for v in obj]
    return obj


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_schema_document() -> dict[str, Any]:
    """Full event+command+snapshot JSON Schema surface for hashing."""
    schema = ContractCatalog.model_json_schema(mode="validation", by_alias=True)
    doc = {
        "protocolVersion": PROTOCOL_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "eventTypes": list(RUNTIME_EVENT_TYPES),
        "commandKinds": list(RUNTIME_COMMAND_KINDS),
        "tradeExitReasons": list(TRADE_EXIT_REASONS),
        "managementActions": list(MANAGEMENT_ACTIONS),
        "jsonSchema": schema,
    }
    return _strip_noise(doc)


def compute_schema_hash() -> str:
    doc = build_schema_document()
    payload = _canonical(doc)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
