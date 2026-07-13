from __future__ import annotations

import asyncio
from typing import Any, Callable


class Mt5CommandDispatcher:
    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    async def dispatch(
        self,
        callable_fn: Callable[[], Any],
        *,
        timeout_s: float,
    ) -> Any:
        fut = self._gateway.submit_command(callable_fn)
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(fut)), timeout=timeout_s)
