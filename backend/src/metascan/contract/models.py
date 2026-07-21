"""Hand-written Pydantic v2 models for frontend contract surface.

snake_case internal / camelCase wire aliases.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from metascan.contract.commands import RUNTIME_COMMAND_KINDS
from metascan.contract.enums import MANAGEMENT_ACTIONS, TRADE_EXIT_REASONS
from metascan.contract.events import RUNTIME_EVENT_TYPES


def _alias(name: str) -> str:
    """snake_case -> camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class WireModel(BaseModel):
    """camelCase wire; required-nullable → null; optional default-None → omit."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        serialize_by_alias=True,
        ser_json_by_alias=True,
        alias_generator=_alias,
    )

    @model_serializer(mode="wrap")
    def _wire_serialize(self, handler: Any, info: Any) -> Any:
        data = handler(self)
        if not isinstance(data, dict):
            return data
        by_alias = True
        if info is not None and getattr(info, "by_alias", None) is False:
            by_alias = False
        for name, finfo in type(self).model_fields.items():
            if finfo.is_required():
                continue
            key = name
            if by_alias:
                key = finfo.serialization_alias or finfo.alias or _alias(name)
            if key in data and data[key] is None:
                del data[key]
        return data


def _str_enum(name: str, values: tuple[str, ...]) -> type[Enum]:
    """str Enum with wire values; member names sanitized (dots → underscores)."""
    members = {v.replace(".", "_").replace("-", "_"): v for v in values}
    return Enum(name, members, type=str)  # type: ignore[return-value]


# Closed catalogs → JSON Schema enum + runtime rejection of unknowns
RuntimeEventType = _str_enum("RuntimeEventType", RUNTIME_EVENT_TYPES)
RuntimeCommandKind = _str_enum("RuntimeCommandKind", RUNTIME_COMMAND_KINDS)


# ---------------------------------------------------------------------------
# Enums as Literals (exact TS spellings)
# ---------------------------------------------------------------------------

TradeExitReasonLit = Literal[
    "TP",
    "SL",
    "TRAIL",
    "PARTIAL_FINAL",
    "MANUAL",
    "TIME_EXIT",
    "KILL_SWITCH",
    "BREAKER",
    "OTHER",
]

ManagementActionLit = Literal[
    "BREAK_EVEN",
    "TRAILING_MOVE",
    "PARTIAL_TP",
    "TIME_EXIT",
]

FrontendDataSource = Literal["DEVELOPMENT_FIXTURE", "LOCAL_RUNTIME"]
EventSeverity = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
BrokerEnvironment = Literal["TRIAL", "LIVE"]
ExecutionSemantics = Literal["LIVE"]
TradeDirection = Literal["LONG", "SHORT"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
OrderStatus = Literal[
    "CREATED",
    "VALIDATED",
    "RISK_CHECKED",
    "SAFETY_CHECKED",
    "SUBMITTED",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "TIMED_OUT",
    "EXECUTION_UNKNOWN",
    "RECONCILED",
]
PositionProtection = Literal[
    "PROTECTED",
    "PARTIALLY_PROTECTED",
    "UNPROTECTED",
    "INVALID_PROTECTION",
    "UNKNOWN",
]
PositionState = Literal["OPEN", "CLOSING", "CLOSED", "RECONCILE_REQUIRED"]
PositionManagementSource = Literal["STRATEGY", "MANUAL_OVERRIDE"]
BreakEvenState = Literal["PENDING", "APPLIED", "SKIPPED"]
TrailingMode = Literal["OFF", "FIXED_POINTS", "ATR", "STEP", "STRUCTURE"]
PartialTpLevelState = Literal["PENDING", "EXECUTED", "SKIPPED", "FAILED"]
TimeExitState = Literal["PENDING", "EXECUTED", "DISABLED"]
RuntimeState = Literal[
    "DISCONNECTED",
    "INITIALIZING",
    "DEGRADED",
    "RECONNECTING",
    "RECONCILING",
    "READY",
    "PAUSED",
    "STOPPING",
    "STOPPED",
    "ERROR",
    "KILLED",
]
TradingMode = Literal["TRIAL", "LIVE"]
DataFreshness = Literal["FRESH", "DELAYED", "STALE", "UNAVAILABLE"]
ConnectionState = Literal[
    "CONNECTED",
    "DISCONNECTED",
    "RECONNECTING",
    "DEGRADED",
    "UNKNOWN",
]
Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
LogSeverity = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
StrategyStatus = Literal[
    "DISABLED",
    "IDLE",
    "WARMING_UP",
    "ACTIVE",
    "PAUSED",
    "BLOCKED",
    "DEGRADED",
    "ERROR",
]
BreakerState = Literal["CLOSED", "WARNING", "OPEN", "RECOVERING", "MANUAL_LOCK"]
IncidentStatus = Literal[
    "OPEN",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "MITIGATED",
    "RESOLVED",
]
RuntimeCommandState = Literal[
    "PREPARED",
    "SUBMITTING",
    "ACCEPTED",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED",
    "TIMED_OUT",
    "EXECUTION_UNKNOWN",
    "CANCELLED",
]
OperatorRole = Literal["VIEWER", "OPERATOR", "RISK_MANAGER", "ADMIN"]


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class BreakEvenPlan(WireModel):
    enabled: bool
    trigger_r: float
    offset_points: float
    state: BreakEvenState
    applied_at: str | None


class TrailingPlan(WireModel):
    mode: TrailingMode
    active: bool
    distance_points: float | None
    current_stop_price: float | None
    last_moved_at: str | None
    move_count: int


class PartialTpLevel(WireModel):
    level_id: str
    at_r: float
    close_percent: float
    state: PartialTpLevelState
    executed_at: str | None
    executed_price: float | None
    closed_volume: float | None


class PartialTpPlan(WireModel):
    levels: list[PartialTpLevel]


class TimeExitPlan(WireModel):
    max_hold_until: str | None
    state: TimeExitState


class PositionManagement(WireModel):
    plan_id: str
    source: PositionManagementSource
    break_even: BreakEvenPlan
    trailing: TrailingPlan
    partial_tp: PartialTpPlan
    time_exit: TimeExitPlan
    next_action: str | None
    last_error: str | None
    paused: bool


class Position(WireModel):
    id: str
    broker_ticket: str
    ownership: Literal["BOT_MANAGED", "FOREIGN", "UNKNOWN"]
    data_available: bool
    source_frame_id: int
    observed_at: str | None
    symbol: str
    side: OrderSide
    volume: float
    entry_price: float
    current_price: float
    stop_loss: float | None
    take_profit: float | None
    floating_pnl: float
    realized_pnl: float | None
    risk_amount: float | None
    risk_pct: float | None
    opened_at: str | None
    strategy: str | None
    protection: PositionProtection
    state: PositionState
    r_multiple: float | None
    mfe: float | None
    mae: float | None
    commission: float
    swap: float
    net_pnl: float
    management: PositionManagement | None


class OrderLifecycleEvent(WireModel):
    at: str
    step: str
    detail: str
    latency_ms: float | None = None


class Order(WireModel):
    id: str
    broker_ticket: str | None
    client_request_id: str
    correlation_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    volume: float
    requested_price: float | None
    filled_price: float | None
    stop_loss: float | None
    take_profit: float | None
    slippage: float | None
    strategy: str
    created_at: str
    updated_at: str
    status: OrderStatus
    rejection_reason: str | None
    lifecycle: list[OrderLifecycleEvent]


class ClosedTradePartialFill(WireModel):
    closed_at: str
    price: float
    volume: float
    net_pnl: float


class ClosedTrade(WireModel):
    trade_id: str
    position_id: str
    strategy_id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    exit_price: float
    opened_at: str
    closed_at: str
    holding_seconds: int
    volume_initial: float
    gross_pnl: float
    commission: float
    swap: float
    net_pnl: float
    r_multiple: float | None
    mfe_r: float | None
    mae_r: float | None
    exit_reason: TradeExitReasonLit
    partial_fills: list[ClosedTradePartialFill]
    tags: list[str]


class RuntimeStatus(WireModel):
    id: str
    session_id: str
    version: str
    build_hash: str
    environment: Literal["LOCAL"]
    trading_mode: TradingMode
    state: RuntimeState
    previous_state: RuntimeState
    state_changed_at: str
    state_reason: str
    started_at: str
    uptime_sec: int
    last_heartbeat_at: str
    heartbeat_latency_ms: float
    entries_enabled: bool
    automation_enabled: bool
    hostname: str
    os: str
    pid: int


class SubsystemHealth(WireModel):
    key: str
    label: str
    state: Literal["OK", "DEGRADED", "DOWN", "UNKNOWN"]
    last_heartbeat_at: str
    latency_ms: float | None
    restart_count: int
    current_action: str | None
    last_error: str | None


class BrokerStatus(WireModel):
    broker: str
    server: str
    login_masked: str
    account_mode: TradingMode
    connection: ConnectionState
    trading_permitted: bool
    terminal_version: str
    last_tick_at: str | None
    last_request_at: str
    queue_depth: int
    avg_latency_ms: float
    timeout_count: int
    reconnect_attempts: int


class AccountSnapshot(WireModel):
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    floating_pnl: float | None
    realized_pnl_today: float
    realized_pnl_week: float
    daily_drawdown: float
    max_drawdown: float
    gross_exposure: float
    net_exposure: float
    open_positions: int | None
    pending_orders: int
    trades_today: int
    win_rate: float
    profit_factor: float
    risk_utilization: float
    updated_at: str | None
    freshness: DataFreshness


class Strategy(WireModel):
    id: str
    name: str
    version: str
    symbols: list[str]
    timeframe: str
    status: StrategyStatus
    trading_mode: TradingMode
    entries_enabled: bool
    allocation_pct: float
    pnl_today: float
    drawdown: float
    signals_today: int
    last_signal_at: str | None
    last_execution_at: str | None
    current_bias: Literal["LONG", "SHORT", "FLAT"]
    confidence: float
    open_positions: int
    health: Literal["OK", "DEGRADED", "ERROR"]


class MarketSymbol(WireModel):
    symbol: str
    group: Literal["FX", "METALS", "INDICES", "CRYPTO"] | None
    bid: float
    ask: float
    spread: float
    last: float
    change_pct: float | None
    session_open: bool | None
    trading_permitted: bool
    tick_age_ms: float
    freshness: DataFreshness
    contract_size: float
    tick_size: float
    min_volume: float
    max_volume: float
    volume_step: float
    swap_long: float | None
    swap_short: float | None
    margin_requirement: float | None


class RiskLimit(WireModel):
    key: str
    label: str
    configured: float
    current: float
    unit: Literal["PCT", "USD", "COUNT", "MS", "PRICE"]
    warn_at: float
    breach_at: float
    breached: bool
    changed_at: str
    changed_by: str


class CircuitBreaker(WireModel):
    key: str
    label: str
    state: BreakerState
    trigger_condition: str
    current_value: str
    threshold: str
    triggered_at: str | None
    recovery_condition: str
    manual_reset_allowed: bool
    last_reset_at: str | None


class Alert(WireModel):
    id: str
    severity: Severity
    title: str
    source: str
    created_at: str
    description: str
    suggested_action: str
    acknowledged: bool
    incident_id: str | None = None


class Incident(WireModel):
    id: str
    severity: Severity
    status: IncidentStatus
    title: str
    started_at: str
    duration_sec: int
    source: str
    impact: str
    affected_components: list[str]
    root_cause: str | None
    resolution: str | None


class ReconciliationIssue(WireModel):
    entity: Literal["ORDER", "POSITION"]
    entity_id: str
    runtime_state: str
    broker_state: str
    difference: str
    severity: Severity
    suggested_action: str
    resolved: bool


class ReconciliationSummary(WireModel):
    state: Literal["IDLE", "RUNNING", "OK", "ISSUES", "FAILED"]
    last_run_at: str
    broker_orders: int
    runtime_orders: int
    broker_positions: int
    runtime_positions: int
    missing_orders: int
    unknown_orders: int
    position_mismatches: int
    volume_mismatches: int
    state_mismatches: int
    issues: list[ReconciliationIssue]


class RuntimeEvent(WireModel):
    id: str
    at: str
    severity: LogSeverity
    source: str
    component: str
    message: str
    correlation_id: str | None = None
    order_id: str | None = None
    position_id: str | None = None
    strategy: str | None = None
    symbol: str | None = None
    payload: dict[str, Any] | None = None


class EquityPoint(WireModel):
    at: str
    equity: float
    balance: float
    floating_pnl: float
    drawdown: float


class CockpitSnapshot(WireModel):
    positions_available: bool
    positions_source_frame_id: int | None
    positions_observed_at: str | None
    account_available: bool
    account_source_frame_id: int | None
    account_observed_at: str | None
    runtime: RuntimeStatus
    subsystems: list[SubsystemHealth]
    broker: BrokerStatus
    account: AccountSnapshot
    strategies: list[Strategy]
    positions: list[Position]
    orders: list[Order]
    markets: list[MarketSymbol]
    alerts: list[Alert]
    incidents: list[Incident]
    risk_limits: list[RiskLimit]
    breakers: list[CircuitBreaker]
    reconciliation: ReconciliationSummary
    events: list[RuntimeEvent]
    equity_curve: list[EquityPoint]


class SnapshotMetadata(WireModel):
    runtime_id: str
    boot_id: str
    revision: int
    sequence: int
    generated_at: str
    server_timestamp: str
    protocol_id: str
    protocol_version: str
    schema_version: str
    schema_hash: str
    source: FrontendDataSource


class RuntimeSnapshotEnvelope(WireModel):
    metadata: SnapshotMetadata
    snapshot: CockpitSnapshot


class RuntimeEventEnvelope(WireModel):
    event_id: str
    type: RuntimeEventType  # type: ignore[valid-type]
    runtime_id: str
    boot_id: str
    revision: int
    sequence: int
    occurred_at: str
    emitted_at: str
    received_at: str
    severity: EventSeverity
    source: FrontendDataSource
    payload: Any
    correlation_id: str | None = None
    command_id: str | None = None
    order_id: str | None = None
    position_id: str | None = None
    strategy_id: str | None = None
    incident_id: str | None = None
    reconciliation_run_id: str | None = None


class RuntimeCommandRequest(WireModel):
    client_request_id: str
    idempotency_key: str
    correlation_id: str
    kind: RuntimeCommandKind  # type: ignore[valid-type]
    target_id: str | None = None
    expected_revision: int | None = None
    reason: str | None = None
    parameters: dict[str, Any] | None = None
    submitted_at: str


class RuntimeCommandStatus(WireModel):
    command_id: str
    client_request_id: str
    correlation_id: str
    idempotency_key: str
    kind: RuntimeCommandKind  # type: ignore[valid-type]
    target_id: str | None = None
    state: RuntimeCommandState
    progress: float | None = None
    current_step: str | None = None
    message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    reason: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class CommandCapability(WireModel):
    command: RuntimeCommandKind  # type: ignore[valid-type]
    allowed: bool
    reason: str | None = None
    risk_level: Literal[1, 2, 3, 4]
    requires_reason: bool
    requires_typed_confirmation: bool
    confirmation_phrase: str | None = None


class RuntimeCapabilities(WireModel):
    revision: int
    generated_at: str
    source: FrontendDataSource
    commands: dict[str, CommandCapability]


class RuntimeHandshake(WireModel):
    runtime_name: str
    runtime_version: str
    runtime_id: str
    boot_id: str
    protocol_id: str
    protocol_version: str
    schema_version: str
    schema_hash: str
    capabilities_revision: int
    min_frontend_version: str | None = None
    frontend_version: str | None = None
    supported_features: list[str]
    supported_commands: list[RuntimeCommandKind]  # type: ignore[valid-type]
    broker_provider: Literal["EXNESS"] | None = None
    broker_environment: BrokerEnvironment | None = None
    execution_semantics: ExecutionSemantics | None = None
    source: FrontendDataSource
    observed_at: str


class TradeHistoryPage(WireModel):
    trades: list[ClosedTrade]
    next_cursor: str | None


class PlanChangedPayload(WireModel):
    position_id: str
    plan: PositionManagement


class ActionExecutedPayload(WireModel):
    position_id: str
    plan_id: str
    action: ManagementActionLit
    detail: dict[str, Any] | None = None


class ActionFailedPayload(WireModel):
    position_id: str
    plan_id: str
    action: ManagementActionLit
    reason: str
    retryable: bool
    level_id: str | None = None


# Catalog anchors for schema hash surface
class ContractCatalog(WireModel):
    """Root document whose JSON Schema covers event+command+snapshot surface."""

    protocol_version: str = Field(description="Protocol semver")
    schema_version: str = Field(description="Schema semver")
    event_types: list[str] = Field(description="RUNTIME_EVENT_TYPES")
    command_kinds: list[str] = Field(description="RuntimeCommandKind")
    trade_exit_reasons: list[str] = Field(description="TradeExitReason")
    management_actions: list[str] = Field(description="MANAGEMENT_ACTIONS")
    event_envelope: RuntimeEventEnvelope
    command_request: RuntimeCommandRequest
    command_status: RuntimeCommandStatus
    snapshot_envelope: RuntimeSnapshotEnvelope
    handshake: RuntimeHandshake
    capabilities: RuntimeCapabilities
    closed_trade: ClosedTrade
    trade_history_page: TradeHistoryPage
    plan_changed: PlanChangedPayload
    action_executed: ActionExecutedPayload
    action_failed: ActionFailedPayload


# ensure catalogs referenced (lint / static)
_ = (RUNTIME_EVENT_TYPES, RUNTIME_COMMAND_KINDS, TRADE_EXIT_REASONS, MANAGEMENT_ACTIONS)
