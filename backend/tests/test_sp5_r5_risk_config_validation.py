from __future__ import annotations

import pytest
from metascan.pipeline.risk_config import RiskConfig


def test_verification_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError) as exc:
        RiskConfig(verification_timeout_s=0)
    assert "verification_timeout_s" in str(exc.value)


def test_verification_timeout_negative_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        RiskConfig(verification_timeout_s=-1)
    assert "verification_timeout_s" in str(exc.value)


def test_verify_poll_interval_must_be_positive() -> None:
    with pytest.raises(ValueError) as exc:
        RiskConfig(verify_poll_interval_ms=0)
    assert "verify_poll_interval_ms" in str(exc.value)


def test_verify_poll_interval_negative_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        RiskConfig(verify_poll_interval_ms=-50)
    assert "verify_poll_interval_ms" in str(exc.value)


def test_poll_interval_seconds_exceeds_timeout_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        RiskConfig(verification_timeout_s=1, verify_poll_interval_ms=2000)
    assert "verify_poll_interval_ms" in str(exc.value) and "verification_timeout_s" in str(exc.value)


def test_poll_interval_equals_timeout_boundary() -> None:
    rc = RiskConfig(verification_timeout_s=2, verify_poll_interval_ms=2000)
    assert rc.verification_timeout_s == 2.0
    assert rc.verify_poll_interval_ms == 2000


def test_default_verification_timeout() -> None:
    rc = RiskConfig()
    assert rc.verification_timeout_s == 10.0


def test_default_verify_poll_interval() -> None:
    rc = RiskConfig()
    assert rc.verify_poll_interval_ms == 50
