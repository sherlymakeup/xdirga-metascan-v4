from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True, slots=True)
class InternalCommandRecord:
    command_id: str
    client_request_id: str
    idempotency_key: str
    correlation_id: str
    kind: str
    target_id: str | None
    state: str
    created_at: str
    updated_at: str
    origin: str
    execution_kind: str
    request_json: str
    progress: float | None = None
    current_step: str | None = None
    message: str | None = None
    error_code: str | None = None

    def internal_json(self) -> str:
        return json.dumps({"kind": self.kind, "request": json.loads(self.request_json)}, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_row(cls, row: Any) -> "InternalCommandRecord":
        return cls(
            command_id=row["command_id"],
            client_request_id=row["client_request_id"],
            idempotency_key=row["idempotency_key"],
            correlation_id=row["correlation_id"],
            kind=row["kind"],
            target_id=row["target_id"],
            state=row["state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            origin=row["origin"],
            execution_kind=row["execution_kind"],
            request_json=row["request_json"],
            progress=row["progress"],
            current_step=row["current_step"],
            message=row["message"],
            error_code=row["error_code"],
        )


class InternalEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    side: str
    stopLoss: float | None = None
    takeProfit: float | None = None
    riskFraction: float | None = None
    price: float | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> InternalEntryRequest:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return self

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def to_internal_record(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        correlation_id: str,
        client_request_id: str = "internal",
        created_at: str = "",
    ) -> InternalCommandRecord:
        return InternalCommandRecord(
            command_id,
            client_request_id,
            idempotency_key,
            correlation_id,
            "INTERNAL_ENTRY_MARKET",
            self.symbol,
            "PREPARED",
            created_at,
            created_at,
            "INTERNAL",
            "INTERNAL_ENTRY_MARKET",
            self.canonical_json(),
        )


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    target_id: str | None = None
    volume: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    price: float | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self) -> CommandRequest:
        if self.volume is not None and self.volume <= 0:
            raise ValueError("volume must be positive")
        return self

    @classmethod
    def from_ingress(cls, payload: dict[str, Any]) -> CommandRequest:
        merged = dict(payload.get("parameters") or payload.get("params") or {})
        for wire, internal in (("targetId", "target_id"), ("stopLoss", "stop_loss"), ("takeProfit", "take_profit")):
            if payload.get(wire) is not None:
                merged[internal] = payload[wire]
        for key in ("volume", "price"):
            if payload.get(key) is not None:
                merged[key] = payload[key]
        return cls(kind=payload["kind"], target_id=payload.get("targetId"), **merged)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_canonical_json(cls, value: str) -> CommandRequest:
        return cls.model_validate_json(value)
