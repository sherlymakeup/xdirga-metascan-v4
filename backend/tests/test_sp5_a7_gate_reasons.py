"""SP5 Round 4: Exact A7 gate reason tests.

Proves: RISK_BUDGET_BELOW_MIN_VOLUME, VOLUME_ABOVE_BROKER_MAX,
deterministic multi-breach precedence.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.risk_gate import run_gates


def _facts(**overrides) -> RuntimeFactsProvider:
    base = dict(
        runtime_state="READY", entries_enabled=True,
        safety_mode_active=False, trading_halt=False,
        account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}},
        symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
    )
    base.update(overrides)
    return RuntimeFactsProvider.current(**base)


def test_risk_budget_below_min_volume() -> None:
    """Gate 7 rejects when risk-based volume after floor < volume_min."""
    facts = _facts(account={"equity": 1.0})
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.001)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_risk_fraction=0.01)
    result = run_gates(request, facts.snapshot(), config)
    assert not result.passed
    assert result.reason == "RISK_BUDGET_BELOW_MIN_VOLUME"


def test_volume_above_broker_max() -> None:
    """Gate 7 rejects when risk-based volume > volume_max."""
    facts = _facts(account={"equity": 1_000_000.0})
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.01)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_risk_fraction=0.1)
    result = run_gates(request, facts.snapshot(), config)
    assert not result.passed
    assert result.reason == "VOLUME_ABOVE_BROKER_MAX"


def test_risk_budget_below_min_volume_deterministic_before_max() -> None:
    """When risk fraction produces volume below min, BELOW_MIN fires, not ABOVE_MAX."""
    facts = _facts(account={"equity": 0.5})
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.001)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_risk_fraction=0.01)
    result = run_gates(request, facts.snapshot(), config)
    assert not result.passed
    assert result.reason == "RISK_BUDGET_BELOW_MIN_VOLUME"


def test_multi_breach_precedence_risk_fraction_exceeds_max_before_exposure() -> None:
    """Risk fraction above max fires before exposure limit."""
    provider = _facts()
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.05)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_risk_fraction=0.01, max_positions=0)
    result = run_gates(request, provider.snapshot(), config)
    assert not result.passed
    assert result.reason == "RISK_FRACTION_EXCEEDS_MAX"


def test_multi_breach_precedence_daily_loss_before_sizing() -> None:
    """Daily loss breach fires before sizing (gate 6 before gate 7)."""
    provider = _facts(day_start_balance=10000.0, daily_realized_pnl=-300.0)
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.005)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_daily_loss=0.02)
    result = run_gates(request, provider.snapshot(), config)
    assert not result.passed
    assert result.reason == "DAILY_LOSS_LIMIT_REACHED"


def test_sizing_metadata_invalid_before_below_min_volume() -> None:
    """Invalid sizing metadata (missing tick_size) fires before volume checks."""
    provider = RuntimeFactsProvider.current(
        runtime_state="READY", entries_enabled=True,
        safety_mode_active=False, trading_halt=False,
        account={"equity": 10000.0}, account_age_ms=0,
        positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}},
        symbol_meta={"EURUSD": {"tick_size": None, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
    )
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.005)
    config = RiskConfig(allowed_symbols=("EURUSD",))
    result = run_gates(request, provider.snapshot(), config)
    assert not result.passed
    assert result.reason == "SIZING_METADATA_INVALID"


def test_exact_calibration_forex_below_min_volume() -> None:
    """Forex: equity=100, risk=0.001 → risk_cash=0.1 → volume very small → BELOW_MIN."""
    provider = RuntimeFactsProvider.current(
        runtime_state="READY", entries_enabled=True,
        safety_mode_active=False, trading_halt=False,
        account={"equity": 100.0}, account_age_ms=0,
        positions=(), ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}},
        symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
    )
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095, riskFraction=0.001)
    config = RiskConfig(allowed_symbols=("EURUSD",), max_risk_fraction=0.01)
    result = run_gates(request, provider.snapshot(), config)
    assert not result.passed
    assert result.reason == "RISK_BUDGET_BELOW_MIN_VOLUME"


def test_exact_calibration_xau_above_broker_max() -> None:
    """XAU: very large equity → volume > 1.0 max → ABOVE_MAX."""
    provider = RuntimeFactsProvider.current(
        runtime_state="READY", entries_enabled=True,
        safety_mode_active=False, trading_halt=False,
        account={"equity": 10_000_000.0}, account_age_ms=0,
        positions=(), ticks={"XAUUSD": {"bid": 2300.0, "ask": 2300.0, "age_ms": 0}},
        symbol_meta={"XAUUSD": {"tick_size": 0.01, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
    )
    request = InternalEntryRequest(symbol="XAUUSD", side="BUY", stopLoss=2295.0, riskFraction=0.01)
    config = RiskConfig(allowed_symbols=("XAUUSD",), max_risk_fraction=0.1)
    result = run_gates(request, provider.snapshot(), config)
    assert not result.passed
    assert result.reason == "VOLUME_ABOVE_BROKER_MAX"
