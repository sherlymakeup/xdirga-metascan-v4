from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Intent:
    command_id: str
    kind: str
    volume: float | None = None
    exit_reason: str = "MANUAL"
    correlation_id: str | None = None


class PendingIntentRegistry:
    def __init__(self) -> None:
        self._intents: dict[int, _Intent] = {}
        self._retained: set[int] = set()
        self._entries: dict[str, _Intent] = {}
        self._entry_tickets: dict[str, int] = {}

    def register_entry(self, symbol: str, command_id: str) -> None:
        self._entries[symbol] = _Intent(command_id, "entry")

    def upgrade_entry(self, symbol: str, ticket: int) -> None:
        if symbol in self._entries:
            self._entry_tickets[symbol] = ticket

    def has_pending_entry(self, symbol: str) -> bool:
        return symbol in self._entries

    def entry_command_id(self, symbol: str) -> str | None:
        intent = self._entries.get(symbol)
        return None if intent is None else intent.command_id

    def entry_ticket(self, symbol: str) -> int | None:
        return self._entry_tickets.get(symbol)

    def register_close(self, ticket: int, command_id: str, *, exit_reason: str = "MANUAL", correlation_id: str | None = None) -> None:
        self._intents[ticket] = _Intent(command_id, "close", exit_reason=exit_reason, correlation_id=correlation_id)

    def register_partial(self, ticket: int, volume: float, command_id: str) -> None:
        self._intents[ticket] = _Intent(command_id, "partial", volume)

    def register_modify(self, ticket: int, command_id: str) -> None:
        self._intents[ticket] = _Intent(command_id, "modify")

    def clear(self, ticket: int) -> None:
        self._intents.pop(ticket, None)
        self._retained.discard(ticket)

    def clear_entry(self, symbol: str) -> None:
        self._entries.pop(symbol, None)
        self._entry_tickets.pop(symbol, None)

    def retain_for_reconciliation(self, ticket: int) -> None:
        self._retained.add(ticket)

    def has_pending_close(self, ticket: int) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "close"

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "partial"

    def has_pending_modify(self, ticket: int) -> bool:
        i = self._intents.get(ticket)
        return i is not None and i.kind == "modify"

    def get_exit_reason(self, ticket: int) -> str:
        i = self._intents.get(ticket)
        return i.exit_reason if i is not None else "MANUAL"

    def get_command_id(self, ticket: int) -> str | None:
        i = self._intents.get(ticket)
        return None if i is None else i.command_id

    def get_correlation_id(self, ticket: int) -> str | None:
        i = self._intents.get(ticket)
        return None if i is None else i.correlation_id
