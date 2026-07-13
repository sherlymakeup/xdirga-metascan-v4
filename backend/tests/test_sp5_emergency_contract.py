from __future__ import annotations

from pathlib import Path


SOURCE = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")


def test_emergency_halts_before_sweep_and_orders_precede_positions() -> None:
    start = SOURCE.index("async def _emergency")
    body = SOURCE[start:]
    assert body.index("self.halted, self.entries_enabled = True, False") < body.index('self._bulk(status, "order.cancelAll"')
    assert body.index('"order.cancelAll"') < body.index('"position.closeAll"')
