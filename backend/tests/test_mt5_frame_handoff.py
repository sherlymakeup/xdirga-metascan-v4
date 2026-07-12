from __future__ import annotations

import asyncio
from types import MappingProxyType

import pytest

from metascan.mt5.handoff import LatestFrameSlot
from metascan.mt5.metrics import GatewayMetrics
from metascan.mt5.types import BrokerStateFrame


def _frame(fid: int) -> BrokerStateFrame:
    return BrokerStateFrame(
        frame_id=fid,
        cycle_started_m=0.0,
        cycle_finished_m=0.1,
        cycle_duration_ms=100.0,
        polled_at_wall="2026-07-13T00:00:00Z",
        positions=(),
        account=None,
        ticks=MappingProxyType({}),
        symbol_meta=MappingProxyType({}),
        errors=(),
        mt5_last_error=None,
    )


async def test_offer_take_empty_slot() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)
    slot.offer(_frame(1))
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 1
    assert m.handoff_dropped_count == 0


async def test_coalesce_replaces_and_counts_drop() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)
    slot.offer(_frame(1))
    slot.offer(_frame(2))
    slot.offer(_frame(3))
    assert m.handoff_dropped_count == 2
    assert m.handoff_overrun_active is True
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 3


async def test_take_waits_for_offer() -> None:
    m = GatewayMetrics()
    slot = LatestFrameSlot(m)

    async def later() -> None:
        await asyncio.sleep(0.05)
        slot.offer(_frame(9))

    asyncio.create_task(later())
    f = await asyncio.wait_for(slot.take(), timeout=1.0)
    assert f.frame_id == 9
