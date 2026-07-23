from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from metascan.web.routers import capabilities, commands, handshake, health, history, snapshot, stream


class TokenRedactingFilter(logging.Filter):
    _TOKEN_RE = re.compile(r"([?&])token=[^&]*")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._TOKEN_RE.sub(r"\1token=***", record.getMessage())
            record.args = ()
        return True


def _add_redacting_filter(target: logging.Logger | logging.Handler) -> None:
    if not any(isinstance(filter_, TokenRedactingFilter) for filter_ in target.filters):
        target.addFilter(TokenRedactingFilter())


def create_app() -> FastAPI:
    loggers = tuple(logging.getLogger(name) for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", ""))
    for logger in loggers:
        _add_redacting_filter(logger)
        for handler in logger.handlers:
            _add_redacting_filter(handler)

    app = FastAPI(title="XDirga Metascan V4")

    @app.exception_handler(Exception)
    async def _global(request: Request, exc: Exception) -> JSONResponse:
        # Never expose exc details — static contract error only.
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "code": "INTERNAL_ERROR"},
        )

    # §10.1 authoritative route census
    app.include_router(handshake.router, prefix="/v4")
    app.include_router(capabilities.router, prefix="/v4")
    app.include_router(snapshot.router, prefix="/v4")
    app.include_router(commands.router, prefix="/v4")
    app.include_router(stream.router, prefix="/v4")
    app.include_router(history.router, prefix="/v4")
    app.include_router(health.router, prefix="/v4")

    return app
