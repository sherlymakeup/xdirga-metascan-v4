from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")


def test_pipeline_shields_gateway_future_and_transitions_uncertainty_directly() -> None:
    assert "asyncio.shield(asyncio.wrap_future(future))" in SOURCE
    assert '_unknown(progress, kind, scope, target, "OUTCOME_AMBIGUOUS")' in SOURCE
    assert 'await self._transition(progress, "TIMED_OUT"' not in SOURCE


def test_no_empty_test_modules() -> None:
    for path in Path("tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tests = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
        assert tests, f"empty test module: {path}"
