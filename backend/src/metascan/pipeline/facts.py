from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PendingOrderFact:
    ticket: int
    symbol: str
    magic: int
    volume: float
    orderType: int


@dataclass(frozen=True, slots=True)
class RuntimeFacts:
    captured_monotonic: float
    config_revision: int
    runtime_state: str
    entries_enabled: bool
    safety_mode_active: bool
    trading_halt: bool
    account: Mapping[str, float]
    account_age_ms: float
    positions: tuple[Any, ...]
    pending_orders: tuple[PendingOrderFact, ...]
    ticks: Mapping[str, Mapping[str, float]]
    symbol_meta: Mapping[str, Mapping[str, float | None]]
    day_start_balance: float = 0.0
    daily_realized_pnl: float = 0.0


class RuntimeFactsProvider:
    def __init__(self, facts: RuntimeFacts) -> None:
        self._facts = facts
        self._locks: set[str] = set()

    @classmethod
    def current(cls, *, runtime_state: str, entries_enabled: bool, safety_mode_active: bool, trading_halt: bool, account: Mapping[str, float], account_age_ms: float, positions: tuple[Any, ...], ticks: Mapping[str, Mapping[str, float]], symbol_meta: Mapping[str, Mapping[str, float | None]], pending_orders: tuple[PendingOrderFact, ...] = (), captured_monotonic: float = 0.0, config_revision: int = 0, day_start_balance: float = 0.0, daily_realized_pnl: float = 0.0) -> RuntimeFactsProvider:
        return cls(RuntimeFacts(captured_monotonic, config_revision, runtime_state, entries_enabled, safety_mode_active, trading_halt, MappingProxyType(dict(account)), account_age_ms, tuple(positions), tuple(pending_orders), MappingProxyType({key: MappingProxyType(dict(value)) for key, value in ticks.items()}), MappingProxyType({key: MappingProxyType(dict(value)) for key, value in symbol_meta.items()}), day_start_balance, daily_realized_pnl))

    def snapshot(self) -> RuntimeFacts:
        return self._facts

    def replace(self, facts: RuntimeFacts) -> None:
        self._facts = facts

    def lock_entity(self, entity_id: str) -> bool:
        if entity_id in self._locks:
            return False
        self._locks.add(entity_id)
        return True

    def unlock_entity(self, entity_id: str) -> None:
        self._locks.discard(entity_id)

    def set_trading_halt(self, value: bool) -> None:
        facts = self._facts
        self._facts = RuntimeFacts(facts.captured_monotonic, facts.config_revision, facts.runtime_state, facts.entries_enabled, facts.safety_mode_active, value, facts.account, facts.account_age_ms, facts.positions, facts.pending_orders, facts.ticks, facts.symbol_meta, facts.day_start_balance, facts.daily_realized_pnl)
