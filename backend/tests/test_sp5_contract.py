from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

# SP5_DESIGN.md:17 requires exactly this internal entry wire shape.
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig


def test_internal_entry_request_has_no_volume_field_and_canonical_request_json() -> None:
    request = InternalEntryRequest(symbol="XAUUSDm", side="BUY", stopLoss=2300.0)

    assert "volume" not in InternalEntryRequest.model_fields
    assert request.canonical_json() == json.dumps(
        {"side": "BUY", "stopLoss": 2300.0, "symbol": "XAUUSDm"},
        separators=(",", ":"),
        sort_keys=True,
    )


@pytest.mark.parametrize("side", ["buy", "HOLD", "SELLL"])
def test_internal_entry_request_accepts_only_buy_or_sell(side: str) -> None:
    with pytest.raises(ValidationError):
        InternalEntryRequest(symbol="XAUUSDm", side=side)


# SP5_DESIGN.md:112 fixes defaults and units.
def test_sp5_configuration_defaults_are_authoritative() -> None:
    config = RiskConfig()

    assert config.risk_fraction == 0.005
    assert config.max_risk_fraction == 0.01
    assert config.max_daily_loss == 0.02
    assert config.max_total_volume == 1
    assert config.max_positions == 5
    assert config.gateway_timeout_s == 5
    assert config.verification_timeout_s == 10
    assert config.deviation_points == 20
    assert config.allowed_symbols == ()
