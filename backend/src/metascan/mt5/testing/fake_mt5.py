from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any


class FakeMt5:
    def __init__(self) -> None:
        self._initialized = False
        self._account: SimpleNamespace | None = None
        self._positions: dict[int, SimpleNamespace] = {}
        self._symbols: dict[str, SimpleNamespace] = {}
        self._ticks: dict[str, SimpleNamespace] = {}
        self._last_error: tuple[int, str] = (0, "OK")
        self._fail_counts: dict[str, int] = {}
        self._return_none: set[str] = set()
        self._block_seconds: dict[str, float] = {}
        self.call_threads: list[tuple[str, int]] = []
        self.call_log: list[str] = []
        self._ticks_frozen = False
        self._terminal: SimpleNamespace | None = SimpleNamespace(connected=True, build=4000)

    def _touch(self, name: str) -> bool:
        self.call_log.append(name)
        self.call_threads.append((name, threading.get_ident()))
        sec = self._block_seconds.pop(name, None)
        if sec:
            time.sleep(sec)
        left = self._fail_counts.get(name, 0)
        if left > 0:
            self._fail_counts[name] = left - 1
            self._last_error = (1, f"forced fail {name}")
            return False
        if name in self._return_none:
            self._last_error = (1, f"forced none {name}")
            return False
        return True

    def initialize(self, **kwargs: Any) -> bool:
        if not self._touch("initialize"):
            return False
        self._initialized = True
        self._last_error = (0, "OK")
        return True

    def shutdown(self) -> None:
        self._touch("shutdown")
        self._initialized = False

    def account_info(self) -> SimpleNamespace | None:
        if not self._touch("account_info"):
            return None
        self._last_error = (0, "OK")
        return self._account

    def positions_get(self, *args: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...] | None:
        if not self._touch("positions_get"):
            return None
        self._last_error = (0, "OK")
        return tuple(self._positions.values())

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        if not self._touch("symbol_select"):
            return False
        if symbol in self._symbols:
            self._symbols[symbol].select = enable
        return True

    def symbol_info(self, symbol: str) -> SimpleNamespace | None:
        if not self._touch("symbol_info"):
            return None
        self._last_error = (0, "OK")
        return self._symbols.get(symbol)

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace | None:
        if not self._touch("symbol_info_tick"):
            return None
        self._last_error = (0, "OK")
        return self._ticks.get(symbol)

    def last_error(self) -> tuple[int, str]:
        return self._last_error

    def terminal_info(self) -> SimpleNamespace | None:
        if not self._touch("terminal_info"):
            return None
        return self._terminal

    def set_account(self, **fields: Any) -> None:
        self._account = SimpleNamespace(**fields)

    def set_positions(self, rows: list[dict[str, Any]]) -> None:
        self._positions.clear()
        for r in rows:
            d = dict(r)
            d.setdefault("commission", 0.0)
            d.setdefault("comment", "")
            d.setdefault("time_msc", 0)
            d.setdefault("identifier", d["ticket"])
            self._positions[int(d["ticket"])] = SimpleNamespace(**d)

    def remove_position(self, ticket: int) -> None:
        self._positions.pop(ticket, None)

    def set_volume(self, ticket: int, volume: float) -> None:
        if ticket in self._positions:
            self._positions[ticket].volume = volume

    def set_protection(self, ticket: int, sl: float, tp: float) -> None:
        if ticket in self._positions:
            self._positions[ticket].sl = sl
            self._positions[ticket].tp = tp

    def add_symbol(self, symbol: str, **fields: Any) -> None:
        fields.setdefault("name", symbol)
        fields.setdefault("select", True)
        self._symbols[symbol] = SimpleNamespace(**fields)

    def set_tick(self, symbol: str, bid: float, ask: float, time_msc: int, **extra: Any) -> None:
        self._ticks[symbol] = SimpleNamespace(
            bid=bid, ask=ask, last=extra.get("last", 0.0),
            time_msc=time_msc, volume=extra.get("volume", 0.0),
        )

    def freeze_ticks(self) -> None:
        self._ticks_frozen = True

    def advance_ticks(self, delta_msc: int) -> None:
        for t in self._ticks.values():
            t.time_msc += delta_msc

    def fail_next(self, call_name: str, times: int = 1) -> None:
        self._fail_counts[call_name] = self._fail_counts.get(call_name, 0) + times

    def set_return(self, call_name: str, value: Any) -> None:
        if value is None:
            self._return_none.add(call_name)

    def clear_return(self, call_name: str) -> None:
        self._return_none.discard(call_name)

    def block_call(self, call_name: str, seconds: float) -> None:
        self._block_seconds[call_name] = seconds

    def set_last_error(self, code: int, msg: str) -> None:
        self._last_error = (code, msg)
