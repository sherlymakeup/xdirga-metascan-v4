"""Enum spellings exact to TS; TradeExitReason has MANUAL only (no MANUAL_CLOSE)."""

from __future__ import annotations

from metascan.contract.enums import (
    MANAGEMENT_ACTIONS,
    TRADE_EXIT_REASONS,
    ManagementAction,
    TradeExitReason,
)


def test_trade_exit_reason_exact_ts() -> None:
    expected = {
        "TP",
        "SL",
        "TRAIL",
        "PARTIAL_FINAL",
        "MANUAL",
        "TIME_EXIT",
        "KILL_SWITCH",
        "BREAKER",
        "OTHER",
    }
    assert set(TRADE_EXIT_REASONS) == expected
    assert "MANUAL_CLOSE" not in TRADE_EXIT_REASONS
    assert TradeExitReason.MANUAL.value == "MANUAL"


def test_management_actions_exact_ts() -> None:
    expected = {"BREAK_EVEN", "TRAILING_MOVE", "PARTIAL_TP", "TIME_EXIT"}
    assert set(MANAGEMENT_ACTIONS) == expected
    assert ManagementAction.BREAK_EVEN.value == "BREAK_EVEN"


def test_external_manual_reconciliation_maps_to_manual() -> None:
    """External/manual/operator labels map to MANUAL; no MANUAL_CLOSE in surface."""
    from metascan.contract.enums import map_exit_reason

    assert map_exit_reason("external") == TradeExitReason.MANUAL
    assert map_exit_reason("manual") == TradeExitReason.MANUAL
    assert map_exit_reason("operator") == TradeExitReason.MANUAL
    assert map_exit_reason("user") == TradeExitReason.MANUAL


def test_no_manual_close_literal_in_contract_surface() -> None:
    """MANUAL_CLOSE must not appear in contract packages or catalog constants."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "metascan"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "MANUAL_CLOSE" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
