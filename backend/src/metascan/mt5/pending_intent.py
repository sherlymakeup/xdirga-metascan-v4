from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PendingIntentLookup(Protocol):
    def has_pending_close(self, ticket: int) -> bool: ...
    def has_pending_partial(self, ticket: int, volume: float) -> bool: ...
    def has_pending_modify(self, ticket: int) -> bool: ...
    def get_exit_reason(self, ticket: int) -> str: ...
    def get_command_id(self, ticket: int) -> str | None: ...
    def get_correlation_id(self, ticket: int) -> str | None: ...
    def clear(self, ticket: int) -> None: ...


class NullPendingIntentLookup:
    def has_pending_close(self, ticket: int) -> bool:
        return False

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False

    def has_pending_modify(self, ticket: int) -> bool:
        return False

    def get_exit_reason(self, ticket: int) -> str:
        return "MANUAL"

    def get_command_id(self, ticket: int) -> str | None:
        return None

    def get_correlation_id(self, ticket: int) -> str | None:
        return None

    def clear(self, ticket: int) -> None:
        pass
