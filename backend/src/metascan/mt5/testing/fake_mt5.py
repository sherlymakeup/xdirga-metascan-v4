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
        self._orders: dict[int, SimpleNamespace] = {}
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
        self._order_check_results: list[SimpleNamespace | None | BaseException] = []
        self._order_send_results: list[SimpleNamespace | None | BaseException | tuple[float, SimpleNamespace | None | BaseException] | tuple[str, SimpleNamespace]] = []
        self._history_deals: list[SimpleNamespace] = []
        self.order_check_requests: list[dict[str, Any]] = []
        self.order_send_requests: list[dict[str, Any]] = []
        self._order_send_block_s: float | None = None
        self._order_send_disconnect: bool = False
        self._block_seconds_recurring: dict[str, float] = {}

    def _touch(self, name: str) -> bool:
        self.call_log.append(name)
        self.call_threads.append((name, threading.get_ident()))
        sec = self._block_seconds.pop(name, None)
        if sec is None:
            sec = self._block_seconds_recurring.get(name)
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

    def orders_get(self, *args: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...] | None:
        if not self._touch("orders_get"):
            return None
        self._last_error = (0, "OK")
        return tuple(self._orders.values())

    def history_deals_get(self, *args: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...]:
        self._touch("history_deals_get")
        position = kwargs.get("position")
        if position is None:
            return tuple(self._history_deals)
        return tuple(deal for deal in self._history_deals if int(getattr(deal, "position_id", 0)) == int(position))

    def order_check(self, request: Any) -> SimpleNamespace | None:
        self.order_check_requests.append(dict(request))
        if not self._touch("order_check"):
            return None
        if self._order_check_results:
            outcome = self._order_check_results.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return SimpleNamespace(retcode=0, comment="ok")

    def script_order_check(self, *, retcode: int = 0, comment: str = "ok") -> None:
        self._order_check_results.append(SimpleNamespace(retcode=retcode, comment=comment))

    def script_order_check_none(self) -> None:
        self._order_check_results.append(None)

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

    def set_orders(self, rows: list[dict[str, Any]]) -> None:
        self._orders.clear()
        for row in rows:
            self._orders[int(row["ticket"])] = SimpleNamespace(**row)

    def set_history_deals(self, rows: list[dict[str, Any]]) -> None:
        self._history_deals = [SimpleNamespace(**row) for row in rows]

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

    def order_send(self, request: Any) -> SimpleNamespace | None:
        self.order_send_requests.append(dict(request))
        if not self._touch("order_send"):
            return None
        if self._order_send_disconnect:
            self._order_send_disconnect = False
            raise ConnectionError("broker disconnect mid-call")
        outcome: SimpleNamespace | None | BaseException = SimpleNamespace(retcode=10009, order=99999, deal=99999, comment="done")
        if self._order_send_block_s is not None:
            time.sleep(self._order_send_block_s)
            self._order_send_block_s = None
        if self._order_send_results:
            scripted = self._order_send_results.pop(0)
            if isinstance(scripted, tuple):
                delay, outcome = scripted
                if delay == "sent_unknown":
                    self._history_deals.append(SimpleNamespace(order=outcome.deal, position_id=request.get("position", 0)))
                    raise ConnectionError("sent unknown")
                time.sleep(delay)
            else:
                outcome = scripted
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is not None and getattr(outcome, "deal", 0):
            self._history_deals.append(SimpleNamespace(order=outcome.deal, position_id=request.get("position", 0)))
        return outcome

    def script_order_send(self, *, retcode: int = 10009, order: int = 99999, deal: int = 0, comment: str = "done") -> None:
        self._order_send_results.append(SimpleNamespace(retcode=retcode, order=order, deal=deal, comment=comment))

    def script_order_send_none(self) -> None:
        self._order_send_results.append(None)

    def script_order_send_exception(self, exc: BaseException) -> None:
        self._order_send_results.append(exc)

    def script_order_send_slow(self, seconds: float, *, retcode: int = 10009, order: int = 99999, deal: int = 0) -> None:
        self._order_send_results.append((seconds, SimpleNamespace(retcode=retcode, order=order, deal=deal, comment="done")))

    def script_order_send_sent_unknown(self, *, order: int, deal: int) -> None:
        self._order_send_results.append(("sent_unknown", SimpleNamespace(retcode=10009, order=order, deal=deal, comment="done")))

    def set_order_send_result(self, ticket: int, retcode: int) -> None:
        self.script_order_send(order=ticket, retcode=retcode)

    def block_order_send(self, seconds: float) -> None:
        self._order_send_block_s = seconds

    def fail_order_send_disconnect(self) -> None:
        self._order_send_disconnect = True
