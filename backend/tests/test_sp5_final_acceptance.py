from __future__ import annotations

from decimal import Decimal

from metascan.pipeline.facts import PendingOrderFact, RuntimeFactsProvider
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig
from metascan.pipeline.risk_gate import GATE_NAMES, run_gates


def test_final_sp5_entry_contract_uses_decimal_sizing_and_exact_gates() -> None:
    facts = RuntimeFactsProvider.current(
        runtime_state="READY", entries_enabled=True, safety_mode_active=False, trading_halt=False,
        account={"equity": 10_000.0}, account_age_ms=0, positions=(),
        ticks={"EURUSD": {"bid": 1.1, "ask": 1.1, "age_ms": 0}},
        symbol_meta={"EURUSD": {"tick_size": 0.00001, "tick_value_loss": 1.0, "volume_min": 0.01, "volume_max": 1.0, "volume_step": 0.01, "age_ms": 0}},
        pending_orders=(PendingOrderFact(ticket=7, symbol="EURUSD", magic=999, volume=0.1, orderType=2),),
    ).snapshot()
    result = run_gates(InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.095), facts, RiskConfig(allowed_symbols=("EURUSD",)))
    assert result.passed
    assert result.trace == GATE_NAMES
    assert result.volume == Decimal("0.10")
    assert facts.pending_orders[0].magic == 999
