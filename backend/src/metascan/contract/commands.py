"""Runtime command kind catalog — mirrors RuntimeCommandKind in TS."""

from __future__ import annotations

RUNTIME_COMMAND_KINDS: tuple[str, ...] = (
    "runtime.start",
    "runtime.pause",
    "runtime.resume",
    "runtime.stop",
    "runtime.restart",
    "runtime.reconnectBroker",
    "runtime.reconcile",
    "runtime.disableEntries",
    "runtime.enableEntries",
    "runtime.emergencyKill",
    "strategy.pause",
    "strategy.resume",
    "strategy.disable",
    "order.cancel",
    "order.cancelAll",
    "position.close",
    "position.closePartial",
    "position.modifyProtection",
    "position.closeAll",
    "position.management.pause",
    "position.management.resume",
    "breaker.reset",
    "alert.acknowledge",
    "incident.acknowledge",
    "config.validate",
    "config.apply",
    "config.rollback",
)
