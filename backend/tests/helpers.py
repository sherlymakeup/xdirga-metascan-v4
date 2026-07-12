from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from metascan.contract.models import RuntimeEventEnvelope
from metascan.mt5.types import PositionRow


def make_envelope(
    *,
    event_id: str = "e1",
    type_: str = "command.created",
    runtime_id: str = "rt1",
    boot_id: str = "",
    sequence: int = 0,
    revision: int = 0,
    payload: dict | None = None,
    command_id: str | None = None,
    order_id: str | None = None,
    position_id: str | None = None,
    occurred_at: str = "2026-07-13T00:00:00Z",
) -> RuntimeEventEnvelope:
    return RuntimeEventEnvelope(
        event_id=event_id,
        type=type_,
        runtime_id=runtime_id,
        boot_id=boot_id,
        revision=revision,
        sequence=sequence,
        occurred_at=occurred_at,
        emitted_at=occurred_at,
        received_at=occurred_at,
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload=payload if payload is not None else {},
        command_id=command_id,
        order_id=order_id,
        position_id=position_id,
    )


def event_type(e: Any) -> str:
    t = getattr(e, "type", "")
    return str(t.value if hasattr(t, "value") else t)


def make_position_row(
    ticket: int = 1001,
    *,
    symbol: str = "XAUUSDm",
    magic: int = 240101,
    volume: float = 0.10,
    price_open: float = 2300.0,
    price_current: float = 2301.0,
    sl: float = 2290.0,
    tp: float = 2320.0,
    profit: float = 10.0,
    swap: float = 0.0,
    commission: float = 0.0,
    type: int = 0,
    time_msc: int = 0,
    identifier: int = 0,
    comment: str = "",
) -> PositionRow:
    return PositionRow(
        ticket=ticket,
        symbol=symbol,
        magic=magic,
        volume=volume,
        price_open=price_open,
        price_current=price_current,
        sl=sl,
        tp=tp,
        profit=profit,
        swap=swap,
        commission=commission,
        type=type,
        time_msc=time_msc,
        identifier=identifier or ticket,
        comment=comment,
    )


def default_account(**over: Any) -> dict[str, Any]:
    base = dict(
        login=123456,
        balance=10_000.0,
        equity=10_050.0,
        margin=100.0,
        margin_free=9_900.0,
        margin_level=10050.0,
        currency="USD",
        trade_mode=0,
        margin_mode=2,
    )
    base.update(over)
    return base


def default_symbol_info(name: str, **over: Any) -> dict[str, Any]:
    base = dict(
        name=name,
        digits=2,
        point=0.01,
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_stops_level=0,
        trade_freeze_level=0,
        filling_mode=1,
        trade_mode=4,
        visible=True,
        select=True,
    )
    base.update(over)
    return base
