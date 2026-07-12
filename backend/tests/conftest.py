from __future__ import annotations

from pathlib import Path

import pytest

from helpers import make_envelope  # noqa: F401


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    return tmp_path / "journal.sqlite"
