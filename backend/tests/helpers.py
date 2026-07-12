from __future__ import annotations

from metascan.contract.models import RuntimeEventEnvelope


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
