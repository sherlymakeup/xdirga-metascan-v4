from __future__ import annotations

# SP5_DESIGN.md:13,19: internal entries persist a non-public execution identity.
from metascan.pipeline.request import InternalEntryRequest


def test_internal_entry_persists_execution_identity_without_transport_kind() -> None:
    request = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2295.0)

    record = request.to_internal_record(
        command_id="entry-1", idempotency_key="idem-1", correlation_id="corr-1"
    )

    assert record.origin == "INTERNAL"
    assert record.execution_kind == "INTERNAL_ENTRY_MARKET"
    assert record.kind == "INTERNAL_ENTRY_MARKET"
    assert record.request_json == request.canonical_json()
