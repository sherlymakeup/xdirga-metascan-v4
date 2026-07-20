from __future__ import annotations

# GET /v4/snapshot — §10.3
# Returns RuntimeSnapshotEnvelope { metadata, snapshot: CockpitSnapshot }.
# Snapshot is atomic; partial snapshots are forbidden.
# The sequence captured here is the handoff boundary for race-free SSE splice.
# Contract source: HANDOFF.md §10.3, runtime-types.ts RuntimeSnapshotEnvelope.

import datetime

from fastapi import APIRouter, Depends, Request

from metascan.bus.event_bus import EventBus
from metascan.contract.hash import GOLDEN_SCHEMA_HASH
from metascan.mt5.types import DashboardReadState
from metascan.web.dependencies import get_bus
from metascan.web.security import verify_token

router = APIRouter()

_RUNTIME_ID = "xdirga"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_snapshot() -> dict:
    """Minimal valid CockpitSnapshot for SP4 (no MT5 execution)."""
    now = _now_iso()
    return {
        "positionsAvailable": False,
        "positionsSourceFrameId": None,
        "positionsObservedAt": None,
        "accountAvailable": False,
        "accountSourceFrameId": None,
        "accountObservedAt": None,
        "runtime": {
            "id": _RUNTIME_ID,
            "sessionId": "session-sp4",
            "version": "4.1.0",
            "buildHash": "dev",
            "environment": "LOCAL",
            "tradingMode": "TRIAL",
            "state": "READY",
            "previousState": "INITIALIZING",
            "stateChangedAt": now,
            "stateReason": "SP4_NO_MT5",
            "startedAt": now,
            "uptimeSec": 0,
            "lastHeartbeatAt": now,
            "heartbeatLatencyMs": 0.0,
            "entriesEnabled": False,
            "automationEnabled": False,
            "hostname": "localhost",
            "os": "win32",
            "pid": 0,
        },
        "subsystems": [],
        "broker": {
            "broker": "EXNESS",
            "server": "",
            "loginMasked": "***",
            "accountMode": "TRIAL",
            "connection": "DISCONNECTED",
            "tradingPermitted": False,
            "terminalVersion": "",
            "lastTickAt": None,
            "lastRequestAt": now,
            "queueDepth": 0,
            "avgLatencyMs": 0.0,
            "timeoutCount": 0,
            "reconnectAttempts": 0,
        },
        "account": {
            "currency": "USD",
            "balance": 0.0,
            "equity": 0.0,
            "margin": 0.0,
            "freeMargin": 0.0,
            "marginLevel": 0.0,
            "floatingPnl": 0.0,
            "realizedPnlToday": 0.0,
            "realizedPnlWeek": 0.0,
            "dailyDrawdown": 0.0,
            "maxDrawdown": 0.0,
            "grossExposure": 0.0,
            "netExposure": 0.0,
            "openPositions": 0,
            "pendingOrders": 0,
            "tradesToday": 0,
            "winRate": 0.0,
            "profitFactor": 0.0,
            "riskUtilization": 0.0,
            "updatedAt": None,
            "freshness": "UNAVAILABLE",
        },
        "strategies": [],
        "positions": [],
        "orders": [],
        "markets": [],
        "alerts": [],
        "incidents": [],
        "riskLimits": [],
        "breakers": [],
        "reconciliation": {
            "state": "IDLE",
            "lastRunAt": now,
            "brokerOrders": 0,
            "runtimeOrders": 0,
            "brokerPositions": 0,
            "runtimePositions": 0,
            "missingOrders": 0,
            "unknownOrders": 0,
            "positionMismatches": 0,
            "volumeMismatches": 0,
            "stateMismatches": 0,
            "issues": [],
        },
        "events": [],
        "equityCurve": [],
    }


def _msc_iso(value: int) -> str | None:
    if value <= 0:
        return None
    return datetime.datetime.fromtimestamp(value / 1000, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _ownership(*, magic: int, bot_magic: int | None) -> str:
    if bot_magic is None:
        return "UNKNOWN"
    return "BOT_MANAGED" if magic == bot_magic else "FOREIGN"


def _read_snapshot(state: DashboardReadState, *, now_utc: datetime.datetime) -> dict:
    snapshot = _empty_snapshot()
    snapshot.update({
        "positionsAvailable": state.positions_available,
        "positionsSourceFrameId": state.positions_frame_id if state.positions_observed_at is not None else None,
        "positionsObservedAt": state.positions_observed_at,
        "accountAvailable": state.account_available,
        "accountSourceFrameId": state.account_frame_id,
        "accountObservedAt": state.account_observed_at,
    })
    observed_at = state.last_frame_at or _now_iso()
    connected = state.connection_state == "CONNECTED"
    now_msc = now_utc.timestamp() * 1000
    latest_tick_msc = max((tick.time_msc for tick in state.ticks.values()), default=0)
    last_tick_at = _msc_iso(latest_tick_msc)
    snapshot["runtime"].update({
        "state": "READY" if connected else "DEGRADED",
        "stateReason": f"MT5_{state.connection_state}",
        "lastHeartbeatAt": observed_at,
        "heartbeatLatencyMs": state.poll_latency_ms or 0.0,
    })
    snapshot["broker"].update({
        "connection": state.connection_state,
        "tradingPermitted": False,
        "lastTickAt": last_tick_at,
        "lastRequestAt": observed_at,
        "avgLatencyMs": state.poll_latency_ms or 0.0,
    })
    snapshot["positions"] = [
        {
            "id": f"pos-{position.ticket}",
            "brokerTicket": str(position.ticket),
            "ownership": _ownership(magic=position.magic, bot_magic=state.bot_magic),
            "dataAvailable": state.positions_available,
            "sourceFrameId": state.positions_frame_id,
            "observedAt": state.positions_observed_at,
            "symbol": position.symbol,
            "side": "BUY" if position.type == 0 else "SELL",
            "volume": position.volume,
            "entryPrice": position.price_open,
            "currentPrice": position.price_current,
            "stopLoss": position.sl or None,
            "takeProfit": position.tp or None,
            "floatingPnl": position.profit,
            "realizedPnl": None,
            "riskAmount": None,
            "riskPct": None,
            "openedAt": _msc_iso(position.time_msc),
            "strategy": None,
            "protection": "PROTECTED" if position.sl and position.tp else ("PARTIALLY_PROTECTED" if position.sl or position.tp else "UNPROTECTED"),
            "state": "OPEN",
            "rMultiple": None,
            "mfe": None,
            "mae": None,
            "commission": position.commission,
            "swap": position.swap,
            "netPnl": position.profit + position.swap + position.commission,
            "management": None,
        }
        for position in state.positions
    ]
    snapshot["markets"] = [
        {
            "symbol": tick.symbol,
            "group": None,
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": tick.ask - tick.bid,
            "last": tick.last,
            "changePct": None,
            "sessionOpen": None,
            "tradingPermitted": False,
            "tickAgeMs": max(0.0, now_msc - tick.time_msc),
            "freshness": "FRESH" if connected and max(0.0, now_msc - tick.time_msc) <= state.tick_age_budget_ms else "STALE",
            "contractSize": state.symbol_meta[tick.symbol].trade_contract_size,
            "tickSize": state.symbol_meta[tick.symbol].tick_size,
            "minVolume": state.symbol_meta[tick.symbol].volume_min,
            "maxVolume": state.symbol_meta[tick.symbol].volume_max,
            "volumeStep": state.symbol_meta[tick.symbol].volume_step,
            "swapLong": None,
            "swapShort": None,
            "marginRequirement": None,
        }
        for tick in state.ticks.values()
        if tick.symbol in state.symbol_meta
    ]
    if state.account is not None:
        same_observation = (
            state.account_frame_id is not None
            and state.account_frame_id == state.positions_frame_id
            and state.account_observed_at == state.positions_observed_at
        )
        floating_pnl = sum(position.profit for position in state.positions) if same_observation else None
        open_positions = len(state.positions) if same_observation else None
        snapshot["account"].update({
            "currency": state.account.currency,
            "balance": state.account.balance,
            "equity": state.account.equity,
            "margin": state.account.margin,
            "freeMargin": state.account.free_margin,
            "marginLevel": state.account.margin_level,
            "floatingPnl": floating_pnl,
            "openPositions": open_positions,
            "updatedAt": state.account_observed_at,
            "freshness": "FRESH" if state.account_available else "STALE",
        })
    return snapshot


@router.get("/snapshot")
async def get_snapshot(
    request: Request,
    bus: EventBus = Depends(get_bus),
    _token: str = Depends(verify_token),
) -> dict:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now = now_utc.isoformat().replace("+00:00", "Z")
    consumer = getattr(request.app.state, "consumer", None)
    read_state, boot_id, revision, sequence = await bus.capture_boundary(
        lambda: consumer.dashboard_state() if consumer is not None else None
    )
    return {
        "metadata": {
            "runtimeId": _RUNTIME_ID,
            "bootId": boot_id,
            "revision": revision,
            "sequence": sequence,
            "generatedAt": now,
            "serverTimestamp": now,
            "protocolId": "xdirga-runtime-v4",
            "protocolVersion": "4.1.0",
            "schemaVersion": "1.1.0",
            "schemaHash": GOLDEN_SCHEMA_HASH,
            "source": "LOCAL_RUNTIME",
        },
        "snapshot": _read_snapshot(read_state, now_utc=now_utc) if read_state is not None else _empty_snapshot(),
    }
