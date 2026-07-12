"""Pydantic v2 models: snake_case internal, camelCase wire aliases; secret-safe dump."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from metascan.contract.models import (
    ClosedTrade,
    RuntimeEventEnvelope,
    RuntimeHandshake,
    SnapshotMetadata,
)


def test_closed_trade_camelcase_wire_aliases() -> None:
    trade = ClosedTrade(
        trade_id="t1",
        position_id="p1",
        strategy_id="s1",
        symbol="XAUUSDm",
        direction="LONG",
        entry_price=2000.0,
        exit_price=2010.0,
        opened_at="2026-01-01T00:00:00Z",
        closed_at="2026-01-01T01:00:00Z",
        holding_seconds=3600,
        volume_initial=0.1,
        gross_pnl=100.0,
        commission=-2.0,
        swap=-0.5,
        net_pnl=97.5,
        r_multiple=1.5,
        mfe_r=2.0,
        mae_r=-0.3,
        exit_reason="MANUAL",
        partial_fills=[],
        tags=[],
    )
    # Default dump must serialize by alias (camelCase) without by_alias=True.
    wire = trade.model_dump(mode="json")
    assert wire["tradeId"] == "t1"
    assert wire["positionId"] == "p1"
    assert wire["exitReason"] == "MANUAL"
    assert wire["netPnl"] == 97.5
    assert "trade_id" not in wire
    assert "position_id" not in wire
    assert "exit_reason" not in wire
    assert "net_pnl" not in wire

    raw = trade.model_dump_json()
    parsed = json.loads(raw)
    assert "tradeId" in parsed
    assert "trade_id" not in parsed


def test_event_envelope_camelcase() -> None:
    env = RuntimeEventEnvelope(
        event_id="e1",
        type="trade.closed",
        runtime_id="r1",
        boot_id="b1",
        revision=1,
        sequence=1,
        occurred_at="2026-01-01T00:00:00Z",
        emitted_at="2026-01-01T00:00:00Z",
        received_at="2026-01-01T00:00:00Z",
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload={"tradeId": "t1"},
    )
    wire = env.model_dump(mode="json")
    assert wire["eventId"] == "e1"
    assert wire["runtimeId"] == "r1"
    assert wire["bootId"] == "b1"
    assert "event_id" not in wire
    assert "runtime_id" not in wire


def test_handshake_protocol_versions() -> None:
    hs = RuntimeHandshake(
        runtime_name="XDirga Runtime V4",
        runtime_version="0.1.0",
        runtime_id="r1",
        boot_id="b1",
        protocol_id="xdirga-runtime-v4",
        protocol_version="4.1.0",
        schema_version="1.1.0",
        schema_hash="abc",
        capabilities_revision=1,
        supported_features=["runtime.events"],
        supported_commands=["runtime.pause"],
        source="LOCAL_RUNTIME",
        observed_at="2026-01-01T00:00:00Z",
    )
    wire = hs.model_dump(mode="json")
    assert wire["protocolVersion"] == "4.1.0"
    assert wire["schemaVersion"] == "1.1.0"
    assert "protocol_version" not in wire


def test_snapshot_metadata_camelcase() -> None:
    meta = SnapshotMetadata(
        runtime_id="r1",
        boot_id="b1",
        revision=1,
        sequence=0,
        generated_at="2026-01-01T00:00:00Z",
        server_timestamp="2026-01-01T00:00:00Z",
        protocol_id="xdirga-runtime-v4",
        protocol_version="4.1.0",
        schema_version="1.1.0",
        schema_hash="abc",
        source="LOCAL_RUNTIME",
    )
    wire = meta.model_dump(mode="json")
    assert wire["runtimeId"] == "r1"
    assert wire["protocolVersion"] == "4.1.0"
    assert "runtime_id" not in wire


def test_event_envelope_payload_required() -> None:
    """payload has no default — missing field fails validation (TS required)."""
    base = {
        "eventId": "e1",
        "type": "trade.closed",
        "runtimeId": "r1",
        "bootId": "b1",
        "revision": 1,
        "sequence": 1,
        "occurredAt": "2026-01-01T00:00:00Z",
        "emittedAt": "2026-01-01T00:00:00Z",
        "receivedAt": "2026-01-01T00:00:00Z",
        "severity": "INFO",
        "source": "LOCAL_RUNTIME",
    }
    with pytest.raises(ValidationError):
        RuntimeEventEnvelope.model_validate(base)
    ok = RuntimeEventEnvelope.model_validate({**base, "payload": {"tradeId": "t1"}})
    assert ok.payload == {"tradeId": "t1"}


def test_optional_wire_fields_omitted_not_null() -> None:
    """Optional TS fields (default None) omitted; not serialized as null."""
    env = RuntimeEventEnvelope(
        event_id="e1",
        type="trade.closed",
        runtime_id="r1",
        boot_id="b1",
        revision=1,
        sequence=1,
        occurred_at="2026-01-01T00:00:00Z",
        emitted_at="2026-01-01T00:00:00Z",
        received_at="2026-01-01T00:00:00Z",
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload={},
    )
    wire = env.model_dump(mode="json")
    assert "correlationId" not in wire
    assert "commandId" not in wire
    assert "orderId" not in wire
    raw = json.loads(env.model_dump_json())
    assert "correlationId" not in raw


def test_required_nullable_fields_present_as_null() -> None:
    """TS required-nullable fields serialize as explicit null, not omitted."""
    from metascan.contract.models import TradeHistoryPage

    trade = ClosedTrade(
        trade_id="t1",
        position_id="p1",
        strategy_id="s1",
        symbol="XAUUSDm",
        direction="LONG",
        entry_price=2000.0,
        exit_price=2010.0,
        opened_at="2026-01-01T00:00:00Z",
        closed_at="2026-01-01T01:00:00Z",
        holding_seconds=3600,
        volume_initial=0.1,
        gross_pnl=100.0,
        commission=-2.0,
        swap=-0.5,
        net_pnl=97.5,
        r_multiple=None,
        mfe_r=None,
        mae_r=None,
        exit_reason="MANUAL",
        partial_fills=[],
        tags=[],
    )
    wire = trade.model_dump(mode="json")
    assert "rMultiple" in wire and wire["rMultiple"] is None
    assert "mfeR" in wire and wire["mfeR"] is None
    assert "maeR" in wire and wire["maeR"] is None
    parsed = json.loads(trade.model_dump_json())
    assert parsed["rMultiple"] is None
    assert parsed["mfeR"] is None
    assert parsed["maeR"] is None

    page = TradeHistoryPage(trades=[], next_cursor=None)
    page_wire = page.model_dump(mode="json")
    assert "nextCursor" in page_wire
    assert page_wire["nextCursor"] is None


def test_type_adapter_omits_optional_nulls() -> None:
    """TypeAdapter / FastAPI path uses same wire rules (no model_dump override)."""
    from pydantic import TypeAdapter

    env = RuntimeEventEnvelope(
        event_id="e1",
        type="trade.closed",
        runtime_id="r1",
        boot_id="b1",
        revision=1,
        sequence=1,
        occurred_at="2026-01-01T00:00:00Z",
        emitted_at="2026-01-01T00:00:00Z",
        received_at="2026-01-01T00:00:00Z",
        severity="INFO",
        source="LOCAL_RUNTIME",
        payload={"x": 1},
    )
    adapter = TypeAdapter(RuntimeEventEnvelope)
    data = adapter.dump_python(env, mode="json")
    assert data["eventId"] == "e1"
    assert "correlationId" not in data
    assert "event_id" not in data

    trade = ClosedTrade(
        trade_id="t1",
        position_id="p1",
        strategy_id="s1",
        symbol="X",
        direction="LONG",
        entry_price=1.0,
        exit_price=2.0,
        opened_at="a",
        closed_at="b",
        holding_seconds=1,
        volume_initial=0.1,
        gross_pnl=1.0,
        commission=0.0,
        swap=0.0,
        net_pnl=1.0,
        r_multiple=None,
        mfe_r=None,
        mae_r=None,
        exit_reason="MANUAL",
        partial_fills=[],
        tags=[],
    )
    tdata = TypeAdapter(ClosedTrade).dump_python(trade, mode="json")
    assert tdata["rMultiple"] is None
    assert "rMultiple" in tdata


def test_event_type_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        RuntimeEventEnvelope(
            event_id="e1",
            type="not.a.real.event",
            runtime_id="r1",
            boot_id="b1",
            revision=1,
            sequence=1,
            occurred_at="2026-01-01T00:00:00Z",
            emitted_at="2026-01-01T00:00:00Z",
            received_at="2026-01-01T00:00:00Z",
            severity="INFO",
            source="LOCAL_RUNTIME",
            payload={},
        )


def test_command_kind_rejects_unknown() -> None:
    from metascan.contract.models import RuntimeCommandRequest

    with pytest.raises(ValidationError):
        RuntimeCommandRequest(
            client_request_id="c1",
            idempotency_key="i1",
            correlation_id="x1",
            kind="not.a.command",
            submitted_at="2026-01-01T00:00:00Z",
        )
