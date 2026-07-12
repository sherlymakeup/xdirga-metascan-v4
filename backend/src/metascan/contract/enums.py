"""Authoritative enum spellings matching frontend TS."""

from __future__ import annotations

from enum import Enum


TRADE_EXIT_REASONS: tuple[str, ...] = (
    "TP",
    "SL",
    "TRAIL",
    "PARTIAL_FINAL",
    "MANUAL",
    "TIME_EXIT",
    "KILL_SWITCH",
    "BREAKER",
    "OTHER",
)

MANAGEMENT_ACTIONS: tuple[str, ...] = (
    "BREAK_EVEN",
    "TRAILING_MOVE",
    "PARTIAL_TP",
    "TIME_EXIT",
)


class TradeExitReason(str, Enum):
    TP = "TP"
    SL = "SL"
    TRAIL = "TRAIL"
    PARTIAL_FINAL = "PARTIAL_FINAL"
    MANUAL = "MANUAL"
    TIME_EXIT = "TIME_EXIT"
    KILL_SWITCH = "KILL_SWITCH"
    BREAKER = "BREAKER"
    OTHER = "OTHER"


class ManagementAction(str, Enum):
    BREAK_EVEN = "BREAK_EVEN"
    TRAILING_MOVE = "TRAILING_MOVE"
    PARTIAL_TP = "PARTIAL_TP"
    TIME_EXIT = "TIME_EXIT"


def map_exit_reason(raw: str) -> TradeExitReason:
    """Map broker/reconciliation labels to TS TradeExitReason.

    External/manual/operator closes map to MANUAL only.
    """
    key = raw.strip().upper().replace("-", "_").replace(" ", "_")
    if key in {"EXTERNAL", "MANUAL", "OPERATOR", "USER"}:
        return TradeExitReason.MANUAL
    try:
        return TradeExitReason(key)
    except ValueError:
        return TradeExitReason.OTHER
