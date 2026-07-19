from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from metascan.bus.event_bus import EventBus
from metascan.contract.models import RuntimeEventEnvelope
from metascan.mt5.clocks import MonotonicClock, WallClock, SystemMonotonicClock, SystemWallClock
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.pending_intent import PendingIntentLookup, NullPendingIntentLookup
from metascan.mt5.types import AccountRow, BrokerStateFrame, DashboardReadState, PositionRow, TickRow
from metascan.mt5.mapping import position_id_for, position_payload, closed_trade_payload, protection_for, sl_or_none, tp_or_none

logger = logging.getLogger("metascan.mt5.consumer")


def _envelope(
    *,
    type_: str,
    runtime_id: str,
    wall_iso: str,
    payload: dict,
    severity: str = "INFO",
    position_id: str | None = None,
) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=str(uuid.uuid4()),
        type=type_,  # type: ignore[arg-type]
        runtime_id=runtime_id,
        boot_id="",
        revision=0,
        sequence=0,
        occurred_at=wall_iso,
        emitted_at=wall_iso,
        received_at=wall_iso,
        severity=severity,  # type: ignore[arg-type]
        source="LOCAL_RUNTIME",
        payload=payload,
        position_id=position_id,
    )


class BrokerStateConsumer:
    def __init__(
        self,
        *,
        bus: EventBus,
        slot: LatestFrameSlot,
        metrics: GatewayMetrics,
        bot_magic: int,
        runtime_id: str,
        pending: PendingIntentLookup | None = None,
        mono: MonotonicClock | None = None,
        wall: WallClock | None = None,
        tick_age_budget_ms: float = 1000.0,
        poll_cycle_p95_budget_ms: float = 400.0,
        hard_fail_threshold: int = 5,
        heartbeat_timeout_ms: float = 2000.0,
    ) -> None:
        self._bus = bus
        self._slot = slot
        self._metrics = metrics
        self._bot_magic = bot_magic
        self._runtime_id = runtime_id
        self._pending = pending or NullPendingIntentLookup()
        self._mono = mono or SystemMonotonicClock()
        self._wall = wall or SystemWallClock()
        self._tick_age_budget_ms = tick_age_budget_ms
        self._poll_cycle_p95_budget_ms = poll_cycle_p95_budget_ms
        self._hard_fail_threshold = hard_fail_threshold
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_positions: dict[int, PositionRow] = {}
        self.last_account: AccountRow | None = None
        self.last_ticks: dict[str, TickRow] = {}
        self.last_symbol_meta: dict[str, Any] = {}
        self.dashboard_positions: tuple[PositionRow, ...] = ()
        self.last_frame_id: int = 0
        self.last_frame_at: str | None = None
        self.connection_state: str = "DISCONNECTED"
        self.quarantine_tickets: set[int] = set()
        self._hard_fail_streak: int = 0
        self._last_tick_mono: dict[str, float] = {}
        self._last_tick_msc: dict[str, int] = {}
        self._degrade_reasons: set[str] = set()
        self._last_frame_mono: float = self._mono.monotonic()

    def dashboard_state(self) -> DashboardReadState:
        return DashboardReadState(
            connection_state=self.connection_state,
            account=self.last_account,
            positions=self.dashboard_positions,
            ticks=self.last_ticks,
            symbol_meta=self.last_symbol_meta,
            bot_magic=self._bot_magic,
            tick_age_budget_ms=self._tick_age_budget_ms,
            last_frame_id=self.last_frame_id,
            last_frame_at=self.last_frame_at,
            poll_latency_ms=self._metrics.cycle_p50(),
        )

    def start(self) -> asyncio.Task[None]:
        self._stop.clear()
        self._last_frame_mono = self._mono.monotonic()
        self._task = asyncio.create_task(self._run(), name="broker-state-consumer")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        t = self._task
        if t is not None:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            now_m = self._mono.monotonic()
            elapsed_ms = (now_m - self._last_frame_mono) * 1000.0
            timeout_s = max(0.01, (self.heartbeat_timeout_ms - elapsed_ms) / 1000.0)
            try:
                frame = await asyncio.wait_for(self._slot.take(), timeout=min(0.5, timeout_s))
                self._last_frame_mono = self._mono.monotonic()
                await self.process_frame(frame)
            except asyncio.TimeoutError:
                # Re-calculate elapsed under the heartbeat deadline
                now_m = self._mono.monotonic()
                if (now_m - self._last_frame_mono) * 1000.0 >= self.heartbeat_timeout_ms:
                    await self._handle_heartbeat_timeout()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in consumer loop")

    async def _handle_heartbeat_timeout(self) -> None:
        self._degrade_reasons.add("HARD_FAIL")
        if self.connection_state != "DISCONNECTED":
            prev_state = self.connection_state
            self.connection_state = "DISCONNECTED"
            wall = self._wall.now_iso()
            env_conn = _envelope(
                type_="broker.connection.changed",
                runtime_id=self._runtime_id,
                wall_iso=wall,
                payload={
                    "state": "DISCONNECTED",
                    "previousState": prev_state,
                    "reasons": sorted(list(self._degrade_reasons)),
                },
            )
            await self._bus.publish(env_conn, mutates_state=True)

            env_health = _envelope(
                type_="runtime.health.changed",
                runtime_id=self._runtime_id,
                wall_iso=wall,
                payload={
                    "subsystem": "mt5-gateway",
                    "state": "DOWN",
                    "reasons": sorted(list(self._degrade_reasons)),
                },
            )
            await self._bus.publish(env_health, mutates_state=True)

    async def process_frame(self, frame: BrokerStateFrame) -> list[RuntimeEventEnvelope]:
        published: list[RuntimeEventEnvelope] = []
        try:
            now_m = self._mono.monotonic()
            for sym, tick in frame.ticks.items():
                prev_msc = self._last_tick_msc.get(sym)
                if prev_msc is not None and tick.time_msc > prev_msc:
                    self._last_tick_mono[sym] = now_m
                    self._last_tick_msc[sym] = tick.time_msc
                elif sym not in self._last_tick_msc:
                    self._last_tick_mono[sym] = now_m
                    self._last_tick_msc[sym] = tick.time_msc

            # ponytail: tick budget assumes active trading session configured; SP7/config session calendars provide backstop reconciliation.
            # Check ticks age
            tick_age_degrade = False
            for sym in frame.ticks:
                last_mono = self._last_tick_mono.get(sym)
                if last_mono is not None:
                    if (now_m - last_mono) * 1000.0 > self._tick_age_budget_ms:
                        tick_age_degrade = True

            reasons: set[str] = set()
            if self._metrics.handoff_overrun_active:
                reasons.add("HANDOFF_OVERRUN")
            p95 = self._metrics.cycle_p95()
            if p95 is not None and p95 > self._poll_cycle_p95_budget_ms:
                reasons.add("POLL_P95")
            if tick_age_degrade:
                reasons.add("TICK_AGE")

            foreign = [p for p in frame.positions if p.magic != self._bot_magic]
            new_q = {p.ticket for p in foreign}
            wall = self._wall.now_iso()
            for p in foreign:
                if p.ticket not in self.quarantine_tickets:
                    env = _envelope(
                        type_="alert.created",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload={
                            "id": f"alien-{p.ticket}",
                            "severity": "CRITICAL",
                            "title": "Alien position detected",
                            "source": "mt5-gateway",
                            "createdAt": wall,
                            "description": f"ticket={p.ticket} symbol={p.symbol} magic={p.magic} expected={self._bot_magic}",
                            "suggestedAction": "Close or move foreign position; do not manage via bot",
                            "acknowledged": False,
                        },
                        severity="CRITICAL",
                    )
                    await self._bus.publish(env, mutates_state=True)
                    published.append(env)
            self.quarantine_tickets = new_q
            if new_q:
                reasons.add("ALIEN_POSITION")

            # Determine fail/error state
            is_failed = frame.positions_unavailable or any(e.call == "account_info" for e in frame.errors)
            if is_failed:
                self._hard_fail_streak += 1
            else:
                self._hard_fail_streak = 0

            if self._hard_fail_streak >= self._hard_fail_threshold:
                reasons.add("HARD_FAIL")
                new_state = "DISCONNECTED"
            else:
                if self._hard_fail_streak > 0 or frame.errors:
                    reasons.add("SOFT_ERROR")
                if reasons:
                    new_state = "DEGRADED"
                else:
                    new_state = "CONNECTED"

            self._degrade_reasons = reasons

            if new_state != self.connection_state:
                prev_state = self.connection_state
                self.connection_state = new_state
                env_conn = _envelope(
                    type_="broker.connection.changed",
                    runtime_id=self._runtime_id,
                    wall_iso=wall,
                    payload={
                        "state": new_state,
                        "previousState": prev_state,
                        "reasons": sorted(list(reasons)),
                    },
                )
                await self._bus.publish(env_conn, mutates_state=True)
                published.append(env_conn)

                health_state = "DOWN" if new_state == "DISCONNECTED" else ("DEGRADED" if new_state == "DEGRADED" else "OK")
                env_health = _envelope(
                    type_="runtime.health.changed",
                    runtime_id=self._runtime_id,
                    wall_iso=wall,
                    payload={
                        "subsystem": "mt5-gateway",
                        "state": health_state,
                        "reasons": sorted(list(reasons)),
                    },
                )
                await self._bus.publish(env_health, mutates_state=True)
                published.append(env_health)

            if frame.positions_unavailable:
                self.last_frame_id = frame.frame_id
                return published

            self.dashboard_positions = frame.positions
            managed = {p.ticket: p for p in frame.positions if p.magic == self._bot_magic}

            # Closes
            for ticket in list(self.last_positions.keys()):
                if ticket not in managed:
                    old = self.last_positions[ticket]
                    exit_reason = self._pending.get_exit_reason(ticket)
                    cmd_id = self._pending.get_command_id(ticket)
                    corr_id = self._pending.get_correlation_id(ticket)

                    env_c = _envelope(
                        type_="position.closed",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload={"positionId": position_id_for(ticket), "symbol": old.symbol, "state": "CLOSED"},
                        position_id=position_id_for(ticket),
                    )
                    if cmd_id is not None:
                        env_c = env_c.model_copy(update={"command_id": cmd_id, "correlation_id": corr_id})
                    await self._bus.publish(env_c, mutates_state=True)
                    published.append(env_c)

                    env_t = _envelope(
                        type_="trade.closed",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload=closed_trade_payload(
                            old, closed_at=wall, exit_reason=exit_reason, correlation_id=corr_id,
                        ),
                        position_id=position_id_for(ticket),
                    )
                    if cmd_id is not None:
                        env_t = env_t.model_copy(update={"command_id": cmd_id, "correlation_id": corr_id})
                    await self._bus.publish(env_t, mutates_state=True)
                    published.append(env_t)

                    self._pending.clear(ticket)
                    del self.last_positions[ticket]

            # Opens + updates
            for ticket, new in managed.items():
                if ticket not in self.last_positions:
                    env_o = _envelope(
                        type_="position.opened",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload=position_payload(new, opened_at=wall),
                        position_id=position_id_for(ticket),
                    )
                    await self._bus.publish(env_o, mutates_state=True)
                    published.append(env_o)
                    self.last_positions[ticket] = new
                    continue

                old = self.last_positions[ticket]
                # Check for volume shrink
                if new.volume < old.volume - 1e-12:
                    matched = self._pending.has_pending_partial(ticket, new.volume)
                    cmd_id = self._pending.get_command_id(ticket) if matched else None
                    corr_id = self._pending.get_correlation_id(ticket) if matched else None
                    env_pc = _envelope(
                        type_="position.partially_closed",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload={
                            "positionId": position_id_for(ticket),
                            "previousVolume": old.volume,
                            "newVolume": new.volume,
                            "closedVolume": old.volume - new.volume,
                            "symbol": new.symbol,
                        },
                        position_id=position_id_for(ticket),
                    )
                    env_up = _envelope(
                        type_="position.updated",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload=position_payload(new, opened_at=wall),
                        position_id=position_id_for(ticket),
                    )
                    if cmd_id is not None:
                        metadata = {"command_id": cmd_id, "correlation_id": corr_id}
                        env_pc = env_pc.model_copy(update=metadata)
                        env_up = env_up.model_copy(update=metadata)
                    await self._bus.publish(env_pc, mutates_state=True)
                    await self._bus.publish(env_up, mutates_state=True)
                    published.extend((env_pc, env_up))
                    if matched:
                        self._pending.clear(ticket)
                    self.last_positions[ticket] = new
                    continue

                # Check for protection changed
                if new.sl != old.sl or new.tp != old.tp:
                    if not self._pending.has_pending_modify(ticket):
                        env_pr = _envelope(
                            type_="position.protection_changed",
                            runtime_id=self._runtime_id,
                            wall_iso=wall,
                            payload={
                                "positionId": position_id_for(ticket),
                                "symbol": new.symbol,
                                "protection": protection_for(new.sl, new.tp),
                                "previousStopLoss": sl_or_none(old.sl),
                                "previousTakeProfit": tp_or_none(old.tp),
                                "stopLoss": sl_or_none(new.sl),
                                "takeProfit": tp_or_none(new.tp),
                            },
                            position_id=position_id_for(ticket),
                        )
                        await self._bus.publish(env_pr, mutates_state=True)
                        published.append(env_pr)

                        env_up = _envelope(
                            type_="position.updated",
                            runtime_id=self._runtime_id,
                            wall_iso=wall,
                            payload=position_payload(new, opened_at=wall),
                            position_id=position_id_for(ticket),
                        )
                        await self._bus.publish(env_up, mutates_state=True)
                        published.append(env_up)
                    self.last_positions[ticket] = new
                    continue

                # Check for MTM or other changes
                if (new.price_current != old.price_current or new.profit != old.profit
                        or new.swap != old.swap or new.commission != old.commission
                        or new.volume != old.volume):
                    env_up = _envelope(
                        type_="position.updated",
                        runtime_id=self._runtime_id,
                        wall_iso=wall,
                        payload=position_payload(new, opened_at=wall),
                        position_id=position_id_for(ticket),
                    )
                    await self._bus.publish(env_up, mutates_state=True)
                    published.append(env_up)
                self.last_positions[ticket] = new

            self.last_account = frame.account
            self.last_ticks = dict(frame.ticks)
            self.last_symbol_meta = dict(frame.symbol_meta)
            self.last_frame_id = frame.frame_id
            self.last_frame_at = frame.polled_at_wall
        except Exception:
            logger.exception("diff failed frame_id=%s", frame.frame_id)
        return published
