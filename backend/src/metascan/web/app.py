from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from metascan.web.routers import capabilities, commands, handshake, health, history, snapshot, stream


class TokenRedactingFilter(logging.Filter):
    _TOKEN_RE = re.compile(r"token=[a-zA-Z0-9_\-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._TOKEN_RE.sub("token=***", record.msg)
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(self._TOKEN_RE.sub("token=***", arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True


def create_app() -> FastAPI:
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        logging.getLogger(name).addFilter(TokenRedactingFilter())
    logging.getLogger().addFilter(TokenRedactingFilter())

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
