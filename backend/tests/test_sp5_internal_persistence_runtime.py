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
async def test_internal_entry_persists_internal_xor_record(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.db")
    bus = EventBus(journal)
    await bus.start()
    from metascan.pipeline.facts import RuntimeFactsProvider
    pipeline = CommandPipeline(
        bus=bus,
        gateway=object(),
        risk_config=RiskConfig(),
        facts=RuntimeFactsProvider.current(
            runtime_state="READY", entries_enabled=True, safety_mode_active=False,
            trading_halt=False, account={}, account_age_ms=0, positions=(), ticks={}, symbol_meta={},
        ),
    )
    try:
        await pipeline.submit_internal(
            InternalEntryRequest(symbol="EURUSD", side="BUY", stopLoss=1.0),
            idempotency_key="entry-key",
        )
        row = journal.run_on_writer(
            lambda conn: conn.execute(
                "SELECT origin, execution_kind, record_json, internal_record_json FROM commands"
            ).fetchone()
        )
        assert tuple(row) == ("INTERNAL", "INTERNAL_ENTRY_MARKET", None, '{"kind":"INTERNAL_ENTRY_MARKET","request":{"side":"BUY","stopLoss":1.0,"symbol":"EURUSD"}}')
    finally:
        await bus.close()
