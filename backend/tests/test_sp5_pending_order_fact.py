from __future__ import annotations

from metascan.pipeline.facts import PendingOrderFact


def test_pending_order_fact_is_immutable_minimal_runtime_fact() -> None:
    fact = PendingOrderFact(ticket=7, symbol="EURUSD", magic=240101, volume=0.1, orderType=2)
    assert (fact.ticket, fact.symbol, fact.magic, fact.volume, fact.orderType) == (7, "EURUSD", 240101, 0.1, 2)
