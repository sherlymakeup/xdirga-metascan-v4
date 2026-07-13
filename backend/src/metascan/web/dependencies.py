from __future__ import annotations

from fastapi import Request

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.journal.db import Journal
from metascan.pipeline.command_pipeline import CommandPipeline
from metascan.pipeline.risk_config import RiskConfig


def get_config(request: Request) -> AppConfig:
    raise NotImplementedError("override in tests or wire via app state")


def get_bus(request: Request) -> EventBus:
    raise NotImplementedError("override in tests or wire via app state")


def get_journal(request: Request) -> Journal:
    raise NotImplementedError("override in tests or wire via app state")


def get_pipeline(request: Request) -> CommandPipeline:
    raise NotImplementedError("override in tests or wire via app state")


def get_risk_config(request: Request) -> RiskConfig:
    raise NotImplementedError("override in tests or wire via app state")
