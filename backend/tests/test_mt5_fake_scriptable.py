from __future__ import annotations

import threading
import time

from metascan.mt5.testing.fake_mt5 import FakeMt5


def test_initialize_shutdown_and_account() -> None:
    f = FakeMt5()
    f.set_account(login=1, balance=100.0, equity=100.0, margin=0.0,
                  margin_free=100.0, margin_level=0.0, currency="USD",
                  trade_mode=0, margin_mode=2)
    assert f.initialize(login=1, password="p", server="s") is True
    acc = f.account_info()
    assert acc is not None
    assert acc.login == 1
    f.shutdown()


def test_positions_appear_shrink_remove() -> None:
    f = FakeMt5()
    f.initialize()
    f.set_positions([{
        "ticket": 10, "symbol": "XAUUSDm", "magic": 1, "volume": 0.2,
        "price_open": 1.0, "price_current": 1.1, "sl": 0.9, "tp": 1.2,
        "profit": 1.0, "swap": 0.0, "commission": 0.0, "type": 0,
        "time_msc": 0, "identifier": 10, "comment": "",
    }])
    pos = f.positions_get()
    assert pos is not None and len(pos) == 1
    f.set_volume(10, 0.1)
    assert f.positions_get()[0].volume == 0.1
    f.set_protection(10, 0.8, 1.3)
    p = f.positions_get()[0]
    assert p.sl == 0.8 and p.tp == 1.3
    f.remove_position(10)
    assert f.positions_get() == ()


def test_ticks_set_and_advance() -> None:
    f = FakeMt5()
    f.set_tick("XAUUSDm", 10.0, 10.1, 1000)
    assert f.symbol_info_tick("XAUUSDm").bid == 10.0
    f.advance_ticks(500)
    assert f.symbol_info_tick("XAUUSDm").time_msc == 1500
    f.freeze_ticks()
    assert f._ticks_frozen is True


def test_fail_next_and_last_error() -> None:
    f = FakeMt5()
    f.initialize()
    f.set_account(login=1, balance=1, equity=1, margin=0, margin_free=1,
                  margin_level=0, currency="USD", trade_mode=0, margin_mode=2)
    f.fail_next("account_info", times=1)
    assert f.account_info() is None
    code, msg = f.last_error()
    assert code != 0 or msg
    assert f.account_info() is not None


def test_block_call_sleeps() -> None:
    f = FakeMt5()
    f.initialize()
    f.block_call("positions_get", 0.15)
    t0 = time.monotonic()
    f.positions_get()
    assert time.monotonic() - t0 >= 0.12  # Allow scheduler jitter while proving blocking.


def test_records_thread_ident() -> None:
    f = FakeMt5()
    f.initialize()
    tid = threading.get_ident()
    f.positions_get()
    assert any(c == "positions_get" and t == tid for c, t in f.call_threads)
