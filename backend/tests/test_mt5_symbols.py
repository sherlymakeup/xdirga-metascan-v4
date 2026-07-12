from __future__ import annotations

from metascan.mt5.symbols import resolve_symbol


def test_resolve_appends_suffix() -> None:
    assert resolve_symbol("XAUUSD", "m") == "XAUUSDm"


def test_resolve_empty_suffix() -> None:
    assert resolve_symbol("BTCUSD", "") == "BTCUSD"


def test_no_hardcoded_suffixed_in_symbols_module() -> None:
    from pathlib import Path
    src = Path("src/metascan/mt5/symbols.py").read_text(encoding="utf-8")
    assert "XAUUSDm" not in src
    assert "BTCUSDm" not in src
