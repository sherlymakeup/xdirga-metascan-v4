from __future__ import annotations

# SP5 entry-intent ruling: pre-send symbol scope, then ticket upgrade.
from metascan.pipeline.pending_intent import PendingIntentRegistry


def test_entry_intent_uses_symbol_scope_then_upgrades_to_ticket() -> None:
    intents = PendingIntentRegistry()

    intents.register_entry("XAUUSDm", "entry-1")
    assert intents.has_pending_entry("XAUUSDm")
    assert intents.entry_command_id("XAUUSDm") == "entry-1"

    intents.upgrade_entry("XAUUSDm", 42)
    assert intents.has_pending_entry("XAUUSDm")
    assert intents.has_pending_close(42) is False
    assert intents.entry_ticket("XAUUSDm") == 42
