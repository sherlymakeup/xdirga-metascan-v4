from __future__ import annotations

import math
from decimal import Decimal

import pytest

# SP5_DESIGN.md:54 requires this literal eight-gate sequence and trace.
from metascan.pipeline.facts import RuntimeFacts, RuntimeFactsProvider
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.risk_gate import GATE_NAMES, run_gates


def test_gate_sequence_is_exact_and_trace_records_every_gate() -> None:
    facts = RuntimeFactsProvider.current(
        runtime_state="READY",
        entries_enabled=True,
        safety_mode_active=False,
        trading_halt=False,
        account={"equity": 10_000.0},
        account_age_ms=0,
        positions=(),
        ticks={"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 0}},
        symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
    ).snapshot()

    result = run_gates(InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095), facts, RiskConfig(allowed_symbols=("EURUSD",)))

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
    assert result.passed
    assert result.trace == GATE_NAMES


# SP5_DESIGN.md:21 and :59 require exact internal entry shape and deterministic price rejection.
def test_internal_entry_rejects_price_pending_entries_are_not_supported() -> None:
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, price=1.1)
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={}, symbol_meta={}).snapshot()

    result = run_gates(request, facts, RiskConfig(allowed_symbols=("EURUSD",)))

    assert result.reason == "PENDING_ENTRIES_NOT_SUPPORTED"
    assert result.trace == ("idempotency", "validation")


@pytest.mark.parametrize(("side", "stop_loss", "take_profit"), [("BUY", 1.101, None), ("SELL", 1.099, None), ("BUY", None, 1.099), ("SELL", None, 1.101)])
def test_validation_rejects_side_invalid_protection(side: str, stop_loss: float | None, take_profit: float | None) -> None:
    request = InternalEntryRequest(symbol="EURUSD", side=side, stopLoss=stop_loss, takeProfit=take_profit)
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 0}}, symbol_meta={}).snapshot()

    assert run_gates(request, facts, RiskConfig(allowed_symbols=("EURUSD",))).reason == "VALIDATION_FAILED"


@pytest.mark.parametrize(("side", "stop_loss"), [("BUY", 1.100005), ("SELL", 1.100005)])
def test_stop_loss_validation_uses_liquidation_quote(side: str, stop_loss: float) -> None:
    request = InternalEntryRequest(symbol="EURUSD", side=side, stopLoss=stop_loss)
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 0}}, symbol_meta={}).snapshot()

    assert run_gates(request, facts, RiskConfig(allowed_symbols=("EURUSD",))).reason == "VALIDATION_FAILED"


# SP5_DESIGN.md:120 requires an explicit whitelist and calibration comment.
def test_entry_fails_closed_without_whitelisted_symbol() -> None:
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.10001, "age_ms": 0}}, symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}}).snapshot()

    result = run_gates(InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095), facts, RiskConfig())

    assert result.reason == "ENTRY_NOT_ELIGIBLE"


# SP5_DESIGN.md:64-68 fixes the formula and forex/XAU/BTC calibration fixtures.
@pytest.mark.parametrize(("symbol", "bid", "ask", "stop_loss", "tick_size", "tick_value_loss"), [("EURUSD", 1.1, 1.1, 1.095, 0.00001, 1.0), ("XAUUSD", 2300.0, 2300.0, 2295.0, 0.01, 1.0), ("BTCUSD", 60000.0, 60000.0, 59500.0, 0.01, 0.01)])
def test_hard_sl_sizing_calibration_fixtures(symbol: str, bid: float, ask: float, stop_loss: float, tick_size: float, tick_value_loss: float) -> None:
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={symbol: {"bid": bid, "ask": ask, "age_ms": 0}}, symbol_meta={symbol: {"tick_size": tick_size, "tick_value_loss": tick_value_loss, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}}).snapshot()

    result = run_gates(InternalEntryRequest(symbol=symbol, side="BUY", stopLoss=stop_loss), facts, RiskConfig(allowed_symbols=(symbol,)))

    assert result.passed
    assert result.volume == Decimal("0.10")


@pytest.mark.parametrize("bad", [None, 0.0, -1.0, math.inf, math.nan])
def test_sizing_rejects_invalid_metadata(bad: float | None) -> None:
    facts = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}}, symbol_meta={"EURUSD": {"tick_size": bad, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}}).snapshot()

    assert run_gates(InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095), facts, RiskConfig(allowed_symbols=("EURUSD",))).reason == "INVALID_VOLUME"


# SP5_DESIGN.md:61 and :64 require a failed gate-6 entry to release its symbol scope.
def test_exposure_rejection_releases_symbol_scope() -> None:
    provider = RuntimeFactsProvider.current(runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False, account={"equity": 10_000.0}, account_age_ms=0, positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}}, symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}})
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095)

    assert run_gates(request, provider.snapshot(), RiskConfig(allowed_symbols=("EURUSD",), max_positions=0), provider).reason == "ENTRY_EXPOSURE_LIMIT"
    assert run_gates(request, provider.snapshot(), RiskConfig(allowed_symbols=("EURUSD",)), provider).passed


def test_runtime_facts_provider_requires_explicit_current_facts() -> None:
    with pytest.raises(TypeError):
        RuntimeFactsProvider.current()  # type: ignore[call-arg]
