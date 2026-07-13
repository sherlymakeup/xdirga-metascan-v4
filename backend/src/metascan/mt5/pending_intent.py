from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PendingIntentLookup(Protocol):
    def has_pending_close(self, ticket: int) -> bool: ...
    def has_pending_partial(self, ticket: int, volume: float) -> bool: ...
    def has_pending_modify(self, ticket: int) -> bool: ...


class NullPendingIntentLookup:
    def has_pending_close(self, ticket: int) -> bool:
        return False

    def has_pending_partial(self, ticket: int, volume: float) -> bool:
        return False

    def has_pending_modify(self, ticket: int) -> bool:
        return False
