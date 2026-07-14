from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

from metascan.pipeline.facts import RuntimeFacts, RuntimeFactsProvider
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig

GATE_NAMES = (
    "idempotency", "validation", "safety classification", "mutation scope lock",
    "entry-only eligibility", "entry-only exposure",
    "entry-only hard-SL+risk sizing downward floor", "universal order_check safety asymmetry",
)


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reason: str | None = None
    trace: tuple[str, ...] = ()
    volume: Decimal | None = None
    classification: str | None = None
    target_scope: str | None = None


def _result(passed: bool, reason: str | None, trace: list[str], volume: Decimal | None = None, classification: str | None = "ENTRY", target_scope: str | None = None) -> GateResult:
    return GateResult(passed, reason, tuple(trace), volume, classification, target_scope)


def _decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise InvalidOperation
    return result


def classify(kind: str) -> tuple[str, bool] | None:
    if kind == "INTERNAL_ENTRY_MARKET": return "ENTRY", True
    if kind in {"position.close", "position.closePartial", "position.closeAll"}: return "REDUCE", False
    if kind == "position.modifyProtection": return "PROTECTION", False
    if kind in {"order.cancel", "order.cancelAll"}: return "CANCEL", False
    if kind == "runtime.emergencyKill": return "EMERGENCY", False
    if kind.startswith(("runtime.", "strategy.", "config.", "breaker.", "alert.", "incident.")): return "CONTROL", False
    return None


def run_gates(request: InternalEntryRequest, facts: RuntimeFacts, config: RiskConfig, provider: RuntimeFactsProvider | None = None) -> GateResult:
    trace = [GATE_NAMES[0], GATE_NAMES[1]]
    if request.price is not None: return _result(False, "PENDING_ENTRIES_NOT_SUPPORTED", trace)
    if request.riskFraction is not None and request.riskFraction <= 0: return _result(False, "VALIDATION_FAILED", trace)
    tick = facts.ticks.get(request.symbol)
    entry_price = (tick or {}).get("ask" if request.side == "BUY" else "bid")
    stop_price = (tick or {}).get("bid" if request.side == "BUY" else "ask")
    if request.stopLoss is not None and stop_price is not None and ((request.side == "BUY" and request.stopLoss >= stop_price) or (request.side == "SELL" and request.stopLoss <= stop_price)): return _result(False, "VALIDATION_FAILED", trace)
    if request.takeProfit is not None and entry_price is not None and ((request.side == "BUY" and request.takeProfit <= entry_price) or (request.side == "SELL" and request.takeProfit >= entry_price)): return _result(False, "VALIDATION_FAILED", trace)
    trace.append(GATE_NAMES[2])
    classified = classify("INTERNAL_ENTRY_MARKET")
    if classified is None: return _result(False, "SAFETY_CLASSIFICATION_FAILED", trace)
    trace.append(GATE_NAMES[3])
    scope = f"entry:{request.symbol}"
    if provider is not None and not provider.lock_entity(scope): return _result(False, "MUTATION_SCOPE_LOCKED", trace, classification=classified[0], target_scope=scope)
    trace.append(GATE_NAMES[4])
    meta = facts.symbol_meta.get(request.symbol)
    eligible = request.symbol in config.allowed_symbols and facts.entries_enabled and facts.runtime_state == "READY" and not facts.safety_mode_active and not facts.trading_halt and facts.account_age_ms <= config.account_age_budget_ms and tick is not None and meta is not None and tick.get("age_ms", float("inf")) <= config.tick_age_budget_ms and meta.get("age_ms", float("inf")) <= config.tick_age_budget_ms
    if not eligible:
        if provider: provider.unlock_entity(scope)
        return _result(False, "ENTRY_NOT_ELIGIBLE", trace, classification=classified[0], target_scope=scope)
    trace.append(GATE_NAMES[5])
    risk_fraction = request.riskFraction if request.riskFraction is not None else config.risk_fraction
    try:
        total_volume = sum(Decimal(str(getattr(position, "volume", 0.0))) for position in facts.positions)
        symbol_volume = sum(Decimal(str(getattr(position, "volume", 0.0))) for position in facts.positions if getattr(position, "symbol", None) == request.symbol)
        max_vol = Decimal(str(config.max_total_volume))
        max_per_sym = Decimal(str(config.max_volume_per_symbol))
        if risk_fraction > config.max_risk_fraction:
            if provider: provider.unlock_entity(scope)
            return _result(False, "RISK_FRACTION_EXCEEDS_MAX", trace, classification=classified[0], target_scope=scope)
        if len(facts.positions) >= config.max_positions or total_volume >= max_vol or symbol_volume >= max_per_sym:
            if provider: provider.unlock_entity(scope)
            return _result(False, "ENTRY_EXPOSURE_LIMIT", trace, classification=classified[0], target_scope=scope)
        day_bal = Decimal(str(facts.day_start_balance)) if facts.day_start_balance else Decimal("0")
        if day_bal > 0:
            max_loss = day_bal * Decimal(str(config.max_daily_loss))
            if Decimal(str(facts.daily_realized_pnl)) <= -max_loss:
                if provider: provider.unlock_entity(scope)
                return _result(False, "DAILY_LOSS_LIMIT_REACHED", trace, classification=classified[0], target_scope=scope)
    except (InvalidOperation, TypeError, ValueError):
        if provider: provider.unlock_entity(scope)
        return _result(False, "SIZING_METADATA_INVALID", trace, classification=classified[0], target_scope=scope)
    trace.append(GATE_NAMES[6])
    if request.stopLoss is None:
        if provider: provider.unlock_entity(scope)
        return _result(False, "MISSING_HARD_SL", trace, classification=classified[0], target_scope=scope)
    try:
        assert meta is not None
        equity, risk, price, stop = (_decimal(value) for value in (facts.account.get("equity"), risk_fraction, entry_price, request.stopLoss))
        tick_size, tick_value_loss, volume_min, volume_max, volume_step = (_decimal(meta.get(key)) for key in ("tick_size", "tick_value_loss", "volume_min", "volume_max", "volume_step"))
        risk_cash = equity * risk
        distance = abs(price - stop)
        loss_per_lot = (distance / tick_size) * tick_value_loss
        raw_volume = risk_cash / loss_per_lot
        volume = (raw_volume // volume_step) * volume_step
        if not all(value.is_finite() and value > 0 for value in (risk_cash, distance, loss_per_lot, raw_volume, volume)) or volume * loss_per_lot > risk_cash: raise InvalidOperation
    except (InvalidOperation, DivisionByZero, TypeError, ValueError):
        if provider: provider.unlock_entity(scope)
        return _result(False, "SIZING_METADATA_INVALID", trace, classification=classified[0], target_scope=scope)
    if volume < volume_min:
        if provider: provider.unlock_entity(scope)
        return _result(False, "RISK_BUDGET_BELOW_MIN_VOLUME", trace, classification=classified[0], target_scope=scope)
    if volume > volume_max:
        if provider: provider.unlock_entity(scope)
        return _result(False, "VOLUME_ABOVE_BROKER_MAX", trace, classification=classified[0], target_scope=scope)
    trace.append(GATE_NAMES[7])
    return _result(True, None, trace, volume, classified[0], scope)
