from __future__ import annotations

from metascan.mt5.types import PositionRow


def position_id_for(ticket: int) -> str:
    return str(ticket)


def sl_or_none(sl: float) -> float | None:
    return None if sl == 0.0 else sl


def tp_or_none(tp: float) -> float | None:
    return None if tp == 0.0 else tp


def side_from_type(t: int) -> str:
    return "BUY" if t == 0 else "SELL"


def direction_from_type(t: int) -> str:
    return "LONG" if t == 0 else "SHORT"


def protection_for(sl: float, tp: float) -> str:
    has_sl = sl != 0.0
    has_tp = tp != 0.0
    if has_sl and has_tp:
        return "PROTECTED"
    if has_sl or has_tp:
        return "PARTIALLY_PROTECTED"
    return "UNPROTECTED"


def position_payload(row: PositionRow, *, strategy: str = "unknown", opened_at: str) -> dict:
    pid = position_id_for(row.ticket)
    return {
        "positionId": pid,
        "id": pid,
        "brokerTicket": str(row.ticket),
        "symbol": row.symbol,
        "side": side_from_type(row.type),
        "volume": row.volume,
        "entryPrice": row.price_open,
        "currentPrice": row.price_current,
        "stopLoss": sl_or_none(row.sl),
        "takeProfit": tp_or_none(row.tp),
        "floatingPnl": row.profit,
        "realizedPnl": None,
        "riskAmount": None,
        "riskPct": None,
        "openedAt": opened_at,
        "strategy": strategy,
        "protection": protection_for(row.sl, row.tp),
        "state": "OPEN",
        "rMultiple": None,
        "mfe": None,
        "mae": None,
        "commission": row.commission,
        "swap": row.swap,
        "netPnl": row.profit + row.commission + row.swap,
        "management": None,
    }


def closed_trade_payload(
    row: PositionRow,
    *,
    closed_at: str,
    strategy_id: str = "unknown",
    exit_reason: str = "MANUAL",
    correlation_id: str | None = None,
    deals: tuple[object, ...] | None = None,
) -> dict:
    from metascan.pipeline.outcome_handler import CLOSE_WHITELIST
    if exit_reason not in CLOSE_WHITELIST:
        raise ValueError(f"exitReason {exit_reason!r} not in {CLOSE_WHITELIST!r}")
    if deals is None:
        raise ValueError("deal history required")
    out = tuple(deal for deal in deals if int(getattr(deal, "entry", -1)) == 1)
    if not out:
        raise ValueError("OUT deal history required")
    volume = sum(float(getattr(deal, "volume", 0.0)) for deal in out)
    exit_price = sum(float(getattr(deal, "price", 0.0)) * float(getattr(deal, "volume", 0.0)) for deal in out) / volume
    gross = sum(float(getattr(deal, "profit", 0.0)) for deal in out)
    commission_including_fees = sum(float(getattr(deal, "commission", 0.0)) + float(getattr(deal, "fee", 0.0)) for deal in deals)
    swap = sum(float(getattr(deal, "swap", 0.0)) for deal in deals)
    closed_at = _msc_to_iso(max(int(getattr(deal, "time_msc", 0)) for deal in out))
    opened_at = closed_at if row.time_msc == 0 else _msc_to_iso(row.time_msc)
    net = gross + commission_including_fees + swap
    result = {
        "tradeId": f"t-{row.ticket}", "positionId": position_id_for(row.ticket), "strategyId": strategy_id,
        "symbol": row.symbol, "direction": direction_from_type(row.type), "entryPrice": row.price_open,
        "exitPrice": exit_price, "openedAt": opened_at, "closedAt": closed_at,
        "holdingSeconds": max(0, int((max(int(getattr(deal, "time_msc", 0)) for deal in out) - row.time_msc) / 1000)),
        "volumeInitial": row.volume, "grossPnl": gross, "commission": commission_including_fees, "swap": swap,
        "netPnl": net, "rMultiple": None, "mfeR": None, "maeR": None, "exitReason": exit_reason,
        "partialFills": [] if len(out) == 1 else [
            {"closedAt": _msc_to_iso(int(getattr(deal, "time_msc", 0))), "price": float(getattr(deal, "price", 0.0)), "volume": float(getattr(deal, "volume", 0.0)), "netPnl": float(getattr(deal, "profit", 0.0)) + float(getattr(deal, "commission", 0.0)) + float(getattr(deal, "fee", 0.0)) + float(getattr(deal, "swap", 0.0))}
            for deal in out
        ], "tags": ["deal-reconciled"],
    }
    if correlation_id is not None:
        result["correlationId"] = correlation_id
    return result


def _msc_to_iso(time_msc: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(time_msc / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
