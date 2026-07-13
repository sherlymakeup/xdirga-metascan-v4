from __future__ import annotations

import pytest
import httpx
from typing import AsyncGenerator

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.bus.event_bus import EventBus
from metascan.journal.db import Journal
from metascan.web.app import create_app
from metascan.web.dependencies import get_config, get_bus, get_journal


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
        credentials=Credentials(api_token="test-token-123"),
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


def _make_app(test_config, event_bus, journal_db):
    app = create_app()
    app.dependency_overrides[get_config] = lambda: test_config
    app.dependency_overrides[get_bus] = lambda: event_bus
    app.dependency_overrides[get_journal] = lambda: journal_db
    return app


@pytest.fixture
async def async_client(
    test_config: AppConfig,
    event_bus: EventBus,
    journal_db: Journal,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app = _make_app(test_config, event_bus, journal_db)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def app_client(
    test_config: AppConfig,
    event_bus: EventBus,
    journal_db: Journal,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Alias used by sync-style tests; backed by AsyncClient for correctness."""
    app = _make_app(test_config, event_bus, journal_db)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
