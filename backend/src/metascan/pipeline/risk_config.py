from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class RiskConfig(BaseModel):
    queue_size: int = 64
    risk_fraction: float = 0.005
    max_risk_fraction: float = 0.01
    max_daily_loss: float = 0.02
    max_total_volume: float = 1
    max_positions: int = 5
    tick_age_budget_ms: int = 1000
    account_age_budget_ms: int = 1000
    gateway_timeout_s: float = 5
    verification_timeout_s: float = 10
    deviation_points: int = 20
    allowed_symbols: tuple[str, ...] = ()
    entries_enabled: bool = True
    max_open_positions: int = 5
    max_volume_per_symbol: float = 1.0
    max_daily_loss_pct: float = 0.02
    spread_max_multiple: float = 3.0
    spread_median_window: int = 20
    verify_poll_interval_ms: int = 50

    @model_validator(mode="after")
    def _validate_ranges(self) -> RiskConfig:
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0")
        if self.max_volume_per_symbol <= 0:
            raise ValueError("max_volume_per_symbol must be > 0")
        if self.max_daily_loss_pct < 0:
            raise ValueError("max_daily_loss_pct must be >= 0")
        if self.spread_max_multiple <= 0:
            raise ValueError("spread_max_multiple must be > 0")
        if self.spread_median_window < 3:
            raise ValueError("spread_median_window must be >= 3")
        if self.tick_age_budget_ms <= 0:
            raise ValueError("tick_age_budget_ms must be > 0")
        if self.account_age_budget_ms <= 0:
            raise ValueError("account_age_budget_ms must be > 0")
        if self.gateway_timeout_s <= 0:
            raise ValueError("gateway_timeout_s must be > 0")
        if self.verification_timeout_s <= 0:
            raise ValueError("verification_timeout_s must be > 0")
        if self.verify_poll_interval_ms <= 0:
            raise ValueError("verify_poll_interval_ms must be > 0")
        timeout_seconds = self.verify_poll_interval_ms / 1000
        if timeout_seconds > self.verification_timeout_s:
            raise ValueError(f"verify_poll_interval_ms ({self.verify_poll_interval_ms}ms) must not exceed verification_timeout_s ({self.verification_timeout_s}s) in seconds")
        return self
