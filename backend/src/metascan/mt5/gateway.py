from __future__ import annotations

import asyncio
import logging
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

    @property
    def boot_error(self) -> BaseException | None:
        return self._boot_error

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
                volume_min=float(info.volume_min),
                volume_max=float(info.volume_max),
                volume_step=float(info.volume_step),
                trade_stops_level=int(info.trade_stops_level),
                trade_freeze_level=int(info.trade_freeze_level),
                filling_mode=int(info.filling_mode),
                trade_mode=trade_mode,
                visible=bool(getattr(info, "visible", True)),
            )
            meta[resolved] = sm
            resolved_list.append(resolved)
        self._symbol_meta = meta
        self._resolved_symbols = resolved_list

    def _poll_loop(self) -> None:
        interval = max(MIN_POLL_INTERVAL_MS, min(MAX_POLL_INTERVAL_MS, self._config.poll_interval_ms))
        interval_s = interval / 1000.0
        try:
            while not self._stop.is_set():
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
