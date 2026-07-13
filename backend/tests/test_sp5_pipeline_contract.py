from __future__ import annotations

from metascan.pipeline.outcome_handler import CLOSE_WHITELIST, exit_reason_for
from metascan.pipeline.risk_gate import GATE_NAMES


def test_sp5_gate_names_are_authoritative() -> None:
    assert GATE_NAMES == (
        "idempotency",
        "validation",
        "safety classification",
        "mutation scope lock",
        "entry-only eligibility",
        "entry-only exposure",
        "entry-only hard-SL+risk sizing downward floor",
        "universal order_check safety asymmetry",
    )


def test_close_whitelist_is_exactly_manual_and_kill_switch() -> None:
    assert CLOSE_WHITELIST == frozenset({"MANUAL", "KILL_SWITCH"})


def test_exit_reason_mappings() -> None:
    assert exit_reason_for("position.close") == "MANUAL"
    assert exit_reason_for("position.closeAll") == "MANUAL"
    assert exit_reason_for("position.closePartial") is None
    assert exit_reason_for("runtime.emergencyKill") == "KILL_SWITCH"
