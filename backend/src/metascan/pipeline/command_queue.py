from __future__ import annotations

import asyncio
from metascan.contract.models import RuntimeCommandStatus


class CommandQueueFull(RuntimeError):
    pass


class CommandQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._queue: asyncio.Queue[RuntimeCommandStatus] = asyncio.Queue(maxsize=maxsize)

    def put_nowait(self, item: RuntimeCommandStatus) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            raise CommandQueueFull("Command queue full")

    async def get(self) -> RuntimeCommandStatus:
        return await self._queue.get()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()
