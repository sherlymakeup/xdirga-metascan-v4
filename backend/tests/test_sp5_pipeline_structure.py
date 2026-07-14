from __future__ import annotations

from pathlib import Path


SOURCE = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")


def test_pipeline_shields_gateway_future_and_transitions_uncertainty_directly() -> None:
    assert "asyncio.shield(asyncio.wrap_future(future))" in SOURCE
    assert '_unknown(progress, kind, scope, target, "OUTCOME_AMBIGUOUS", payload)' in SOURCE
    assert 'await self._transition(progress, "TIMED_OUT"' not in SOURCE
