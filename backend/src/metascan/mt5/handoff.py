from __future__ import annotations

import asyncio

from metascan.mt5.types import BrokerStateFrame
from metascan.mt5.metrics import GatewayMetrics


class LatestFrameSlot:
    def __init__(self, metrics: GatewayMetrics) -> None:
        self._frame: BrokerStateFrame | None = None
        self._event = asyncio.Event()
        self._metrics = metrics

    def offer(self, frame: BrokerStateFrame) -> None:
        if self._frame is not None:
            self._metrics.note_handoff_drop()
        self._frame = frame
        self._event.set()

    async def take(self) -> BrokerStateFrame:
        while True:
            await self._event.wait()
            frame = self._frame
            if frame is None:
                self._event.clear()
                continue
            self._frame = None
            self._event.clear()
            return frame

    def peek(self) -> BrokerStateFrame | None:
        return self._frame
