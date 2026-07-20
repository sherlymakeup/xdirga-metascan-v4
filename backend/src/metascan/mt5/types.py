from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


@dataclass(frozen=True, slots=True)
class GatewayError:
    call: str
    code: int
    message: str


@dataclass(frozen=True, slots=True)
class PositionRow:
    ticket: int
    symbol: str
    magic: int
    volume: float
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    swap: float
    commission: float
    type: int
    time_msc: int
    identifier: int
    comment: str


@dataclass(frozen=True, slots=True)
class AccountRow:
    login: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
    trade_mode: int
    margin_mode: int


@dataclass(frozen=True, slots=True)
class TickRow:
    symbol: str
    bid: float
    ask: float
    last: float
    time_msc: int
    volume: float


@dataclass(frozen=True, slots=True)
class SymbolMeta:
    base: str
    resolved: str
    digits: int
    point: float
    trade_contract_size: float
    tick_size: float
    tick_value_loss: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_stops_level: int
    trade_freeze_level: int
    filling_mode: int
    trade_mode: int
    visible: bool


@dataclass(frozen=True, slots=True)
class DashboardReadState:
    connection_state: Literal["CONNECTED", "DISCONNECTED", "DEGRADED"]
    account: AccountRow | None
    positions: tuple[PositionRow, ...]
    ticks: Mapping[str, TickRow]
    symbol_meta: Mapping[str, SymbolMeta]
    bot_magic: int | None
    tick_age_budget_ms: float
    last_frame_id: int
    last_frame_at: str | None
    poll_latency_ms: float | None
    positions_available: bool = True
    positions_frame_id: int = 0
    positions_observed_at: str | None = None
    account_available: bool = False
    account_frame_id: int | None = None
    account_observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.connection_state not in {"CONNECTED", "DISCONNECTED", "DEGRADED"}:
            raise ValueError("invalid dashboard connection state")
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "ticks", MappingProxyType(dict(self.ticks)))
        object.__setattr__(self, "symbol_meta", MappingProxyType(dict(self.symbol_meta)))
        if self.positions_available:
            object.__setattr__(self, "positions_frame_id", self.last_frame_id)
            object.__setattr__(self, "positions_observed_at", self.last_frame_at)
        if self.account_available:
            object.__setattr__(self, "account_frame_id", self.last_frame_id)
            object.__setattr__(self, "account_observed_at", self.last_frame_at)

    def with_frame(
        self,
        *,
        connection_state: Literal["CONNECTED", "DISCONNECTED", "DEGRADED"],
        account: AccountRow | None,
        ticks: Mapping[str, TickRow],
        symbol_meta: Mapping[str, SymbolMeta],
        last_frame_id: int,
        last_frame_at: str,
        poll_latency_ms: float | None,
        positions: tuple[PositionRow, ...] | None,
    ) -> DashboardReadState:
        return DashboardReadState(
            connection_state=connection_state,
            account=self.account if account is None else account,
            positions=self.positions if positions is None else positions,
            ticks=ticks,
            symbol_meta=symbol_meta,
            bot_magic=self.bot_magic,
            tick_age_budget_ms=self.tick_age_budget_ms,
            last_frame_id=last_frame_id,
            last_frame_at=last_frame_at,
            poll_latency_ms=poll_latency_ms,
            positions_available=positions is not None,
            positions_frame_id=self.positions_frame_id,
            positions_observed_at=self.positions_observed_at,
            account_available=account is not None,
            account_frame_id=self.account_frame_id,
            account_observed_at=self.account_observed_at,
        )


@dataclass(frozen=True, slots=True)
class ConsumerFrameState:
    connection_state: Literal["CONNECTED", "DISCONNECTED", "DEGRADED"]
    quarantine_tickets: frozenset[int]
    hard_fail_streak: int
    last_tick_mono: Mapping[str, float]
    last_tick_msc: Mapping[str, int]
    degrade_reasons: frozenset[str]
    last_positions: Mapping[int, PositionRow]
    dashboard: DashboardReadState
    pending_clears: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_tick_mono", MappingProxyType(dict(self.last_tick_mono)))
        object.__setattr__(self, "last_tick_msc", MappingProxyType(dict(self.last_tick_msc)))
        object.__setattr__(self, "last_positions", MappingProxyType(dict(self.last_positions)))


@dataclass(frozen=True, slots=True)
class BrokerStateFrame:
    frame_id: int
    cycle_started_m: float
    cycle_finished_m: float
    cycle_duration_ms: float
    polled_at_wall: str
    positions: tuple[PositionRow, ...]
    account: AccountRow | None
    ticks: Mapping[str, TickRow]
    symbol_meta: Mapping[str, SymbolMeta]
    errors: tuple[GatewayError, ...]
    mt5_last_error: tuple[int, str] | None
    positions_unavailable: bool = False
