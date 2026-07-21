from __future__ import annotations

from fastapi import Request

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.risk_config import RiskConfig


def get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is not None:
        return config
    raise NotImplementedError("override in tests or wire via app state")


def get_bus(request: Request) -> EventBus:
    bus = getattr(request.app.state, "bus", None)
    if bus is not None:
        return bus
    raise NotImplementedError("override in tests or wire via app state")


def get_journal(request: Request) -> Journal:
    raise NotImplementedError("override in tests or wire via app state")


def get_pipeline(request: Request) -> CommandPipeline:
    raise NotImplementedError("override in tests or wire via app state")


def get_risk_config(request: Request) -> RiskConfig:
    raise NotImplementedError("override in tests or wire via app state")
