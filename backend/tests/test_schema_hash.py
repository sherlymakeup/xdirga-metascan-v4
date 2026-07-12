"""Canonical schema hash: deterministic SHA-256 over event+command+snapshot schemas."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from metascan.contract.hash import (
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    compute_schema_hash,
    GOLDEN_SCHEMA_HASH,
)


def test_protocol_and_schema_versions() -> None:
    assert PROTOCOL_VERSION == "4.1.0"
    assert SCHEMA_VERSION == "1.1.0"


def test_hash_is_stable_sha256_hex() -> None:
    h1 = compute_schema_hash()
    h2 = compute_schema_hash()
    assert h1 == h2
    assert re.fullmatch(r"[0-9a-f]{64}", h1)


def test_golden_schema_hash_pinned() -> None:
    assert compute_schema_hash() == GOLDEN_SCHEMA_HASH
    assert re.fullmatch(r"[0-9a-f]{64}", GOLDEN_SCHEMA_HASH)


def test_cli_hash_matches_twice() -> None:
    backend = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "metascan.contract", "hash"]
    env = {**dict(**__import__("os").environ), "PYTHONPATH": str(backend / "src")}
    r1 = subprocess.run(cmd, cwd=backend, capture_output=True, text=True, env=env, check=False)
    r2 = subprocess.run(cmd, cwd=backend, capture_output=True, text=True, env=env, check=False)
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    out1 = r1.stdout.strip()
    out2 = r2.stdout.strip()
    assert out1 == out2
    assert out1 == GOLDEN_SCHEMA_HASH


def test_schema_document_strips_non_semantic_noise() -> None:
    from metascan.contract.hash import build_schema_document

    def _assert_no_noise(obj: object) -> None:
        if isinstance(obj, dict):
            assert "title" not in obj
            assert "description" not in obj
            for v in obj.values():
                _assert_no_noise(v)
        elif isinstance(obj, list):
            for v in obj:
                _assert_no_noise(v)

    _assert_no_noise(build_schema_document())
