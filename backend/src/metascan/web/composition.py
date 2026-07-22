from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from metascan.bus.event_bus import EventBus
from metascan.config import AppConfig
from metascan.journal.db import Journal
from metascan.mt5.consumer import BrokerStateConsumer
from metascan.mt5.gateway import GatewayBootError, GatewayConfig, Mt5Gateway
from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.web.app import create_app

logger = logging.getLogger("metascan.web.composition")


def _resolve_mt5_module(mt5_module: Any) -> Any | None:
    if mt5_module is not None:
        return mt5_module
    login = os.environ.get("MT5_LOGIN", "").strip()
    password = os.environ.get("MT5_PASSWORD", "").strip()
    server = os.environ.get("MT5_SERVER", "").strip()
    if not (login and password and server):
        return None
    try:
        import MetaTrader5  # type: ignore[import-untyped]
        return MetaTrader5
    except ImportError:
        return None


def create_wired_app(
    *,
    mt5_module: Any = None,
    config: AppConfig | None = None,
    bot_magic: int | None = None,
    watchlist_bases: tuple[str, ...] = ("XAUUSD",),
    symbol_suffix: str = "m",
    journal_path: str | None = None,
) -> FastAPI:
    resolved_module = _resolve_mt5_module(mt5_module)

    if bot_magic is None:
        env_magic = os.environ.get("BOT_MAGIC", "").strip()
        bot_magic = int(env_magic) if env_magic else 0

    owns_journal_path = journal_path is None
    if journal_path is None:
        journal_fd, journal_path = tempfile.mkstemp(
            prefix="metascan-journal-", suffix=".sqlite"
        )
        os.close(journal_fd)
    journal = Journal(journal_path)
    journal.open()

    bus = EventBus(journal)
    gateway: Mt5Gateway | None = None
    consumer: BrokerStateConsumer | None = None

    app = create_app()

    @asynccontextmanager
    async def lifespan(a: FastAPI):  # noqa: ARG001
        nonlocal gateway, consumer
        await bus.start()
        a.state.bus = bus
        a.state.journal = journal
        if config is not None:
            a.state.config = config

        if resolved_module is not None:
            metrics = GatewayMetrics()
            slot = LatestFrameSlot(metrics)
            loop = asyncio.get_running_loop()

            login_str = os.environ.get("MT5_LOGIN", "").strip()
            password_str = os.environ.get("MT5_PASSWORD", "").strip()
            server_str = os.environ.get("MT5_SERVER", "").strip()

            cfg = GatewayConfig(
                login=int(login_str) if login_str.isdigit() else None,
                password=password_str,
                server=server_str,
                symbol_suffix=symbol_suffix,
                watchlist_bases=watchlist_bases,
                bot_magic=bot_magic,
            )
            gateway = Mt5Gateway(
                resolved_module,
                config=cfg,
                slot=slot,
                loop=loop,
                metrics=metrics,
            )
            try:
                gateway.start()
                gateway.wait_boot()
            except (GatewayBootError, TimeoutError) as exc:
                logger.error("gateway boot failed: %s", exc)
                gateway.stop()
                gateway = None
            else:
                consumer = BrokerStateConsumer(
                    bus=bus,
                    slot=slot,
                    metrics=metrics,
                    bot_magic=bot_magic,
                    runtime_id="xdirga",
                )
                consumer.start()
                a.state.consumer = consumer

        yield

        if consumer is not None:
            await consumer.stop()
        if gateway is not None:
            gateway.stop()
        await bus.close()
        journal.close()
        if owns_journal_path:
            for path in (
                journal.path,
                journal.path.with_name(f"{journal.path.name}-shm"),
                journal.path.with_name(f"{journal.path.name}-wal"),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    app.router.lifespan_context = lifespan

    return app
