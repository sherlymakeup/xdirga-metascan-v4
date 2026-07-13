from __future__ import annotations

EXIT_REASON_MAP = {
    "position.close": "MANUAL",
    "position.closeAll": "MANUAL",
    "runtime.emergencyKill": "KILL_SWITCH",
}

CLOSE_WHITELIST = frozenset({"MANUAL", "KILL_SWITCH"})


def exit_reason_for(command_kind: str) -> str | None:
    return EXIT_REASON_MAP.get(command_kind)


def is_terminal(state: str) -> bool:
    return state in ("COMPLETED", "FAILED", "EXECUTION_UNKNOWN", "CANCELLED")
