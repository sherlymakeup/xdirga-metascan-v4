from __future__ import annotations

# SP3 forbade order_send entirely (mutations out of scope);
# superseded in SP5 by the seam invariant below.
import asyncio
import concurrent.futures
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Sequence
from types import MappingProxyType

from metascan.mt5.clocks import MonotonicClock, WallClock, SystemMonotonicClock, SystemWallClock
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.symbols import resolve_symbol
from metascan.mt5.types import (
    AccountRow, BrokerStateFrame, GatewayError, PositionRow, SymbolMeta, TickRow,
)

logger = logging.getLogger("metascan.mt5.gateway")

DEFAULT_POLL_INTERVAL_MS = 250
MIN_POLL_INTERVAL_MS = 50
MAX_POLL_INTERVAL_MS = 2000
ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
_NO_POSITIONS_CODES = frozenset({0})


class GatewayBootError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    login: int | None
    password: str
    server: str
    symbol_suffix: str
    watchlist_bases: tuple[str, ...]
    bot_magic: int
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS
    require_hedging: bool = True
    path: str | None = None


class Mt5Gateway:
    def __init__(
        self,
        mt5_module: Any,
        *,
        config: GatewayConfig,
        slot: LatestFrameSlot,
        loop: asyncio.AbstractEventLoop,
        metrics: GatewayMetrics,
        mono: MonotonicClock | None = None,
        wall: WallClock | None = None,
    ) -> None:
        self._mt5 = mt5_module
        self._config = config
        self._slot = slot
        self._loop = loop
        self._metrics = metrics
        self._mono = mono or SystemMonotonicClock()
        self._wall = wall or SystemWallClock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._boot_ok = threading.Event()
        self._boot_error: BaseException | None = None
        self._frame_id = 0
        self._symbol_meta: dict[str, SymbolMeta] = {}
        self._resolved_symbols: list[str] = []
        self._cmd_queue: queue.Queue[tuple[Callable, concurrent.futures.Future]] = queue.Queue()

    @property
    def boot_error(self) -> BaseException | None:
        return self._boot_error

    @property
    def thread_id(self) -> int | None:
        return self._thread.ident if self._thread is not None else None

    def submit_command(self, fn: Callable[[], Any]) -> concurrent.futures.Future:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._cmd_queue.put((fn, fut))
        return fut

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("gateway already started")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="mt5-gateway", daemon=True
        )
        self._thread.start()

    def wait_boot(self, timeout: float = 5.0) -> None:
        if not self._boot_ok.wait(timeout):
            raise TimeoutError("gateway boot timeout")
        if self._boot_error is not None:
            raise GatewayBootError(str(self._boot_error)) from self._boot_error

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=join_timeout)
        self._thread = None

    def _run(self) -> None:
        try:
            self._boot()
            self._boot_ok.set()
        except BaseException as exc:
            self._boot_error = exc
            self._boot_ok.set()
            return
        self._poll_loop()

    def _boot(self) -> None:
        mt5 = self._mt5
        cfg = self._config
        kwargs: dict[str, Any] = {"password": cfg.password, "server": cfg.server}
        if cfg.login is not None:
            kwargs["login"] = cfg.login
        if cfg.path:
            kwargs["path"] = cfg.path
        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            raise GatewayBootError(f"initialize failed: {err}")
        acc = mt5.account_info()
        if acc is None:
            raise GatewayBootError(f"account_info failed: {mt5.last_error()}")
        if cfg.login is not None and int(acc.login) != int(cfg.login):
            raise GatewayBootError(
                f"login mismatch: expected {cfg.login} got {acc.login}"
            )
        margin_mode = int(getattr(acc, "margin_mode", -1))
        if cfg.require_hedging and margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
            raise GatewayBootError(
                f"hedging required: margin_mode={margin_mode} expected {ACCOUNT_MARGIN_MODE_RETAIL_HEDGING}"
            )
        meta: dict[str, SymbolMeta] = {}
        resolved_list: list[str] = []
        for base in cfg.watchlist_bases:
            resolved = resolve_symbol(base, cfg.symbol_suffix)
            if not mt5.symbol_select(resolved, True):
                raise GatewayBootError(
                    f"symbol_select failed base={base} resolved={resolved}: {mt5.last_error()}"
                )
            info = mt5.symbol_info(resolved)
            if info is None or not getattr(info, "visible", True):
                raise GatewayBootError(
                    f"symbol missing/invisible base={base} resolved={resolved}"
                )
            trade_mode = int(getattr(info, "trade_mode", 0))
            if trade_mode == 0:
                raise GatewayBootError(
                    f"symbol trading disabled base={base} resolved={resolved}"
                )
            sm = SymbolMeta(
                base=base,
                resolved=resolved,
                digits=int(info.digits),
                point=float(info.point),
                trade_contract_size=float(info.trade_contract_size),
                tick_size=float(getattr(info, "trade_tick_size", getattr(info, "tick_size", 0.0)) or 0.0),
                tick_value_loss=float(getattr(info, "trade_tick_value_loss", 0.0) or 0.0),
                volume_min=float(info.volume_min),
                volume_max=float(info.volume_max),
                volume_step=float(info.volume_step),
                trade_stops_level=int(info.trade_stops_level),
                trade_freeze_level=int(info.trade_freeze_level),
                filling_mode=int(info.filling_mode),
                trade_mode=trade_mode,
                visible=bool(getattr(info, "visible", True)),
            )
            if sm.tick_size <= 0 or sm.tick_value_loss <= 0:
                raise GatewayBootError(f"invalid tick metadata base={base} resolved={resolved}")
            meta[resolved] = sm
            resolved_list.append(resolved)
        self._symbol_meta = meta
        self._resolved_symbols = resolved_list

    def _poll_loop(self) -> None:
        interval = max(MIN_POLL_INTERVAL_MS, min(MAX_POLL_INTERVAL_MS, self._config.poll_interval_ms))
        interval_s = interval / 1000.0
        try:
            while not self._stop.is_set():
                self._drain_commands()
                t0 = self._mono.monotonic()
                try:
                    frame = self._one_cycle(t0)
                except Exception as exc:
                    logger.exception("poll cycle error")
                    self._frame_id += 1
                    frame = BrokerStateFrame(
                        frame_id=self._frame_id,
                        cycle_started_m=t0,
                        cycle_finished_m=self._mono.monotonic(),
                        cycle_duration_ms=(self._mono.monotonic() - t0) * 1000.0,
                        polled_at_wall=self._wall.now_iso(),
                        positions=(),
                        account=None,
                        ticks=MappingProxyType({}),
                        symbol_meta=MappingProxyType(dict(self._symbol_meta)),
                        errors=(GatewayError("one_cycle_exception", 9999, str(exc)),),
                        mt5_last_error=None,
                        positions_unavailable=True,
                    )
                try:
                    self._handoff(frame)
                    self._metrics.record_cycle_ms(frame.cycle_duration_ms)
                    if frame.cycle_duration_ms > interval:
                        self._metrics.note_cycle_overrun()
                except RuntimeError as rexc:
                    if "Event loop is closed" in str(rexc):
                        logger.warning("Event loop closed; stopping gateway poll")
                        break
                    logger.exception("handoff failed")
                except Exception:
                    logger.exception("handoff failed")
                elapsed = self._mono.monotonic() - t0
                remaining = interval_s - elapsed
                if remaining > 0:
                    self._stop.wait(remaining)
        finally:
            try:
                self._mt5.shutdown()
            except Exception:
                logger.exception("shutdown failed")

    def _one_cycle(self, t0: float) -> BrokerStateFrame:
        mt5 = self._mt5
        errors: list[GatewayError] = []
        positions_unavailable = False
        c0 = self._mono.monotonic()
        raw_pos = mt5.positions_get()
        self._metrics.record_call_ms("positions_get", (self._mono.monotonic() - c0) * 1000)
        positions: list[PositionRow] = []
        if raw_pos is None:
            code, msg = mt5.last_error()
            if code in _NO_POSITIONS_CODES:
                positions = []
            else:
                positions_unavailable = True
                errors.append(GatewayError("positions_get", code, msg))
        else:
            for p in raw_pos:
                positions.append(PositionRow(
                    ticket=int(p.ticket),
                    symbol=str(p.symbol),
                    magic=int(p.magic),
                    volume=float(p.volume),
                    price_open=float(p.price_open),
                    price_current=float(p.price_current),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    profit=float(p.profit),
                    swap=float(p.swap),
                    commission=float(getattr(p, "commission", 0.0) or 0.0),
                    type=int(p.type),
                    time_msc=int(getattr(p, "time_msc", 0) or 0),
                    identifier=int(getattr(p, "identifier", p.ticket)),
                    comment=str(getattr(p, "comment", "") or ""),
                ))
        c1 = self._mono.monotonic()
        raw_acc = mt5.account_info()
        self._metrics.record_call_ms("account_info", (self._mono.monotonic() - c1) * 1000)
        account = None
        if raw_acc is None:
            code, msg = mt5.last_error()
            errors.append(GatewayError("account_info", code, msg))
        else:
            account = AccountRow(
                login=int(raw_acc.login),
                balance=float(raw_acc.balance),
                equity=float(raw_acc.equity),
                margin=float(raw_acc.margin),
                free_margin=float(raw_acc.margin_free),
                margin_level=float(raw_acc.margin_level),
                currency=str(raw_acc.currency),
                trade_mode=int(raw_acc.trade_mode),
                margin_mode=int(raw_acc.margin_mode),
            )
        ticks: dict[str, TickRow] = {}
        c2 = self._mono.monotonic()
        for sym in self._resolved_symbols:
            t = mt5.symbol_info_tick(sym)
            if t is None:
                code, msg = mt5.last_error()
                errors.append(GatewayError("symbol_info_tick", code, f"{sym}: {msg}"))
                continue
            ticks[sym] = TickRow(
                symbol=sym,
                bid=float(t.bid),
                ask=float(t.ask),
                last=float(getattr(t, "last", 0.0) or 0.0),
                time_msc=int(getattr(t, "time_msc", 0) or 0),
                volume=float(getattr(t, "volume", 0.0) or 0.0),
            )
        self._metrics.record_call_ms(
            "symbol_info_tick", (self._mono.monotonic() - c2) * 1000
        )
        t1 = self._mono.monotonic()
        self._frame_id += 1
        le = mt5.last_error()
        return BrokerStateFrame(
            frame_id=self._frame_id,
            cycle_started_m=t0,
            cycle_finished_m=t1,
            cycle_duration_ms=(t1 - t0) * 1000.0,
            polled_at_wall=self._wall.now_iso(),
            positions=tuple(positions),
            account=account,
            ticks=MappingProxyType(ticks),
            symbol_meta=MappingProxyType(dict(self._symbol_meta)),
            errors=tuple(errors),
            mt5_last_error=le if le else None,
            positions_unavailable=positions_unavailable,
        )

    def _handoff(self, frame: BrokerStateFrame) -> None:
        self._loop.call_soon_threadsafe(self._slot.offer, frame)

    def _drain_commands(self) -> None:
        while True:
            try:
                fn, fut = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fut.set_result(fn())
            except BaseException as exc:
                fut.set_exception(exc)

    def _constant(self, name: str, fallback: int) -> int:
        return int(getattr(self._mt5, name, fallback))

    def order_check(self, request: dict[str, Any]) -> concurrent.futures.Future:
        return self.submit_command(lambda: self._mt5.order_check(request))

    def mutation(self, command_id: str, kind: str, target_id: str | None, request: dict[str, Any], *, reason: str = "MANUAL") -> Any:
        return self.submit_command(lambda: self._mutation_on_gateway_thread(command_id, kind, target_id, request, reason))

    def success_retcodes(self) -> frozenset[int]:
        return frozenset({self._constant("TRADE_RETCODE_DONE", 10009), self._constant("TRADE_RETCODE_DONE_PARTIAL", 10010)})

    def sweep_facts(self) -> concurrent.futures.Future:
        return self.submit_command(self._sweep_facts_on_gateway_thread)

    def _sweep_facts_on_gateway_thread(self) -> dict[str, Any]:
        orders = self._mt5.orders_get()
        positions = self._mt5.positions_get()
        return {
            "orders": tuple({"ticket": int(row.ticket), "symbol": str(row.symbol), "magic": int(row.magic), "volume": float(getattr(row, "volume_current", getattr(row, "volume", 0.0))), "orderType": int(row.type)} for row in (orders or ())),
            "positions": tuple({"ticket": int(p.ticket), "symbol": str(p.symbol), "magic": int(p.magic), "volume": float(p.volume), "type": int(p.type)} for p in (positions or ())),
        }

    def verify(self, target_id: str | None) -> concurrent.futures.Future:
        return self.submit_command(lambda: self._verify_on_gateway_thread(target_id))

    def _verify_on_gateway_thread(self, target_id: str | None) -> dict[str, Any]:
        positions = self._mt5.positions_get()
        orders = self._mt5.orders_get() if hasattr(self._mt5, "orders_get") else ()
        ticket = int(target_id) if target_id and target_id.isdigit() else None
        position_found = any(int(p.ticket) == ticket for p in positions or ()) if ticket else None
        order_found = any(int(o.ticket) == ticket for o in orders or ()) if ticket else None
        deals = self._mt5.history_deals_get() if hasattr(self._mt5, "history_deals_get") else ()
        return {
            "positionExists": position_found,
            "orderExists": order_found,
            "positions": positions or (),
            "orders": orders or (),
            "deals": deals,
            "ticket": ticket,
        }

    def _mutation_on_gateway_thread(self, command_id: str, kind: str, target_id: str | None, request: dict[str, Any], reason: str) -> Any:
        mt5 = self._mt5
        deal = self._constant("TRADE_ACTION_DEAL", 1)
        sltp = self._constant("TRADE_ACTION_SLTP", 6)
        remove = self._constant("TRADE_ACTION_REMOVE", 8)
        buy = self._constant("ORDER_TYPE_BUY", 0)
        sell = self._constant("ORDER_TYPE_SELL", 1)
        positions = {int(p.ticket): p for p in (mt5.positions_get() or ())}
        if kind in {"position.open", "order.open", "INTERNAL_ENTRY_MARKET"}:
            symbol = str(request["symbol"])
            meta = self._symbol_meta[symbol]
            side = str(request["side"]).upper()
            if side not in {"BUY", "SELL"}:
                raise ValueError("INVALID_SIDE")
            tick = mt5.symbol_info_tick(symbol)
            req = {"action": deal, "symbol": symbol, "volume": float(request["volume"]), "type": buy if side == "BUY" else sell, "price": float(tick.ask if side == "BUY" else tick.bid), "magic": self._config.bot_magic, "deviation": int(request.get("deviation", 20)), "type_filling": meta.filling_mode, "comment": f"{command_id[:17]} CALIBRATE-SP6"}
            if request.get("stop_loss") is not None:
                req["sl"] = float(request["stop_loss"])
            if request.get("take_profit") is not None:
                req["tp"] = float(request["take_profit"])
            return self._checked_send(mt5, req, allow_unavailable_check=False)
        if kind in {"position.close", "position.closePartial"}:
            if target_id is None or int(target_id) not in positions:
                raise ValueError("POSITION_NOT_FOUND")
            p = positions[int(target_id)]
            meta = self._symbol_meta[p.symbol]
            tick = mt5.symbol_info_tick(p.symbol)
            volume = float(p.volume) if kind == "position.close" else self._normalize_partial(float(request.get("volume", 0)), float(p.volume), meta)
            req = {"action": deal, "position": int(p.ticket), "symbol": p.symbol, "volume": volume, "type": sell if int(p.type) == buy else buy, "price": float(tick.bid if int(p.type) == buy else tick.ask), "magic": self._config.bot_magic, "deviation": int(request.get("deviation", 20)), "type_filling": meta.filling_mode, "comment": command_id}
            return self._checked_send(mt5, req, allow_unavailable_check=True)
        if kind == "position.modifyProtection":
            if target_id is None or int(target_id) not in positions:
                raise ValueError("POSITION_NOT_FOUND")
            p = positions[int(target_id)]
            req = {"action": sltp, "position": int(p.ticket), "symbol": p.symbol, "sl": float(request["stop_loss"]) if request.get("stop_loss") is not None else float(p.sl), "tp": float(request["take_profit"]) if request.get("take_profit") is not None else float(p.tp), "magic": self._config.bot_magic, "comment": command_id}
            return self._checked_send(mt5, req, allow_unavailable_check=True)
        if kind == "order.cancel":
            if target_id is None:
                raise ValueError("ORDER_NOT_FOUND")
            return self._checked_send(mt5, {"action": remove, "order": int(target_id), "magic": self._config.bot_magic, "comment": command_id}, allow_unavailable_check=True)
        raise ValueError("UNSUPPORTED_COMMAND")

    def _checked_send(self, mt5: Any, request: dict[str, Any], *, allow_unavailable_check: bool) -> Any:
        checked = mt5.order_check(request)
        if checked is None:
            if allow_unavailable_check:
                return mt5.order_send(request)
            raise ValueError("ORDER_CHECK_UNAVAILABLE")
        if getattr(checked, "retcode", 0) not in {0, *self.success_retcodes()}:
            return checked
        return mt5.order_send(request)

    @staticmethod
    def _normalize_partial(requested: float, current: float, meta: SymbolMeta) -> float:
        from decimal import Decimal, InvalidOperation
        try:
            r = Decimal(str(requested))
            c = Decimal(str(current))
            vstep = Decimal(str(meta.volume_step))
            vmin = Decimal(str(meta.volume_min))
        except (InvalidOperation, ValueError):
            raise ValueError("PARTIAL_CLOSE_INVALID_VOLUME")
        if r <= 0:
            raise ValueError("PARTIAL_CLOSE_INVALID_VOLUME")
        if r < vmin:
            raise ValueError("PARTIAL_CLOSE_BELOW_MIN_VOLUME")
        floor = (r // vstep) * vstep
        if floor < vmin:
            raise ValueError("PARTIAL_CLOSE_BELOW_MIN_VOLUME")
        remainder = c - floor
        if remainder > 0 and remainder < vmin:
            raise ValueError("PARTIAL_CLOSE_DUST_REMAINDER")
        if floor >= c:
            raise ValueError("PARTIAL_CLOSE_EXCEEDS_CURRENT")
        return float(floor)
