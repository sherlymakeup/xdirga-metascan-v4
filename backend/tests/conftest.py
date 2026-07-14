from __future__ import annotations

import ast
from pathlib import Path

import pytest

from helpers import make_envelope  # noqa: F401


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> None:
    if file_path.suffix != ".py" or not file_path.name.startswith("test_sp5"):
        return None
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    tests = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
    if not tests or not any(any(isinstance(child, ast.Assert) for child in ast.walk(test)) for test in tests):
        raise pytest.UsageError(f"empty or assertion-free SP5 test module: {file_path}")
    return None


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    return tmp_path / "journal.sqlite"
