from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


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
