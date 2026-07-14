from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.request import InternalEntryRequest
from metascan.pipeline.risk_config import RiskConfig


@pytest.mark.asyncio
async def test_internal_entry_replay_is_not_enqueued_twice(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.db")
    bus = EventBus(journal)
    await bus.start()
    from metascan.pipeline.facts import RuntimeFactsProvider
    pipeline = CommandPipeline(
        bus=bus,
        gateway=object(),
        risk_config=RiskConfig(),
        bot_magic=999,
        facts=RuntimeFactsProvider.current(
            runtime_state="READY", entries_enabled=True, safety_mode_active=False,
            trading_halt=False, account={}, account_age_ms=0, positions=(), ticks={}, symbol_meta={},
        ),
    )
    request = InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.0)
    try:
        first = await pipeline.submit_internal(request, idempotency_key="entry-key")
        replay = await pipeline.submit_internal(request, idempotency_key="entry-key")
        assert replay.command_id == first.command_id
        assert journal.run_on_writer(lambda conn: conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0]) == 1
        assert journal.run_on_writer(lambda conn: conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]) == 1
    finally:
        await bus.close()
