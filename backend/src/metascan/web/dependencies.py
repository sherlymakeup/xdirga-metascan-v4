from __future__ import annotations

from fastapi import Request

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.journal.db import Journal


def get_config(request: Request) -> AppConfig:
    raise NotImplementedError("override in tests or wire via app state")


def get_bus(request: Request) -> EventBus:
    raise NotImplementedError("override in tests or wire via app state")


def get_journal(request: Request) -> Journal:
    raise NotImplementedError("override in tests or wire via app state")
