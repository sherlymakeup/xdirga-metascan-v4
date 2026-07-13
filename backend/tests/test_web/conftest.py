from __future__ import annotations

import pytest
import httpx
from typing import AsyncGenerator

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.pending_intent import PendingIntentRegistry
from metascan.pipeline.facts import RuntimeFactsProvider
from metascan.pipeline.risk_config import RiskConfig
from metascan.web.app import create_app
from metascan.web.dependencies import get_config, get_bus, get_journal, get_pipeline


@pytest.fixture
def test_config() -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(
            runtime_name="XDirga Runtime V4",
            protocol_id="xdirga-runtime-v4",
            protocol_version="4.1.0",
            schema_version="1.1.0",
            broker_provider="EXNESS",
            broker_environment="TRIAL",
            execution_semantics="LIVE",
        ),
        credentials=Credentials(api_token="FAKE-TEST-TOKEN-NOT-REAL"),
    )


@pytest.fixture
def journal_db(tmp_path) -> Journal:
    db_path = tmp_path / "test.sqlite"
    j = Journal(db_path)
    j.open()
    yield j
    j.close()


@pytest.fixture
async def event_bus(journal_db: Journal) -> EventBus:
    bus = EventBus(journal_db)
    await bus.start()
    yield bus
    await bus.close()


@pytest.fixture
async def pipeline_stub(event_bus: EventBus) -> CommandPipeline:
    pending = PendingIntentRegistry()
    risk_config = RiskConfig()
    p = CommandPipeline(
        bus=event_bus,
        gateway=None,
        risk_config=risk_config,
        pending=pending,
        facts=RuntimeFactsProvider.current(
            runtime_state="READY", entries_enabled=True, safety_mode_active=False,
            trading_halt=False, account={}, account_age_ms=0, positions=(), ticks={}, symbol_meta={},
        ),
        bot_magic=0,
        runtime_id="rt-test",
    )
    yield p
    await p.stop()


def _make_app(test_config, event_bus, journal_db, pipeline_stub):
    app = create_app()
    app.dependency_overrides[get_config] = lambda: test_config
    app.dependency_overrides[get_bus] = lambda: event_bus
    app.dependency_overrides[get_journal] = lambda: journal_db
    app.dependency_overrides[get_pipeline] = lambda: pipeline_stub
    return app


@pytest.fixture
async def async_client(
    test_config: AppConfig,
    event_bus: EventBus,
    journal_db: Journal,
    pipeline_stub: CommandPipeline,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app = _make_app(test_config, event_bus, journal_db, pipeline_stub)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def app_client(
    test_config: AppConfig,
    event_bus: EventBus,
    journal_db: Journal,
    pipeline_stub: CommandPipeline,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app = _make_app(test_config, event_bus, journal_db, pipeline_stub)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
