"""Drift guard: parse authoritative TS registries; exact set equality."""

from __future__ import annotations

import re
from pathlib import Path

from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.enums import MANAGEMENT_ACTIONS, TRADE_EXIT_REASONS
from metascan.contract.events import RUNTIME_EVENT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
TS_ROOT = REPO_ROOT / "src" / "lib"


def _read(rel: str) -> str:
    return (TS_ROOT / rel).read_text(encoding="utf-8")


def _parse_string_array(source: str, const_name: str) -> set[str]:
    """Parse `export const NAME = [ "a", "b", ... ] as const`."""
    m = re.search(
        rf"export const {re.escape(const_name)}\s*=\s*\[(.*?)]\s*as const",
        source,
        re.DOTALL,
    )
    assert m, f"const {const_name} not found"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _parse_string_union(source: str, type_name: str) -> set[str]:
    """Parse `export type Name = | "a" | "b"` or `= "a" | "b"`."""
    m = re.search(
        rf"export type {re.escape(type_name)}\s*=\s*(.*?);",
        source,
        re.DOTALL,
    )
    assert m, f"type {type_name} not found"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_event_types_match_ts_registry() -> None:
    # Authoritative list lives in runtime-event-envelope.ts (imported by event-schemas).
    src = _read("runtime/events/runtime-event-envelope.ts")
    ts = _parse_string_array(src, "RUNTIME_EVENT_TYPES")
    assert set(RUNTIME_EVENT_TYPES) == ts


def test_command_kinds_match_ts_union() -> None:
    src = _read("runtime/runtime-types.ts")
    ts = _parse_string_union(src, "RuntimeCommandKind")
    assert set(RUNTIME_COMMAND_KINDS) == ts


def test_management_actions_match_ts() -> None:
    src = _read("runtime/events/event-schemas.ts")
    ts = _parse_string_array(src, "MANAGEMENT_ACTIONS")
    assert set(MANAGEMENT_ACTIONS) == ts


def test_trade_exit_reason_match_ts() -> None:
    src = _read("types.ts")
    ts = _parse_string_union(src, "TradeExitReason")
    assert set(TRADE_EXIT_REASONS) == ts
    assert "MANUAL_CLOSE" not in ts
