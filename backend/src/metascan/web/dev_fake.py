# Dev-only entrypoint: runs the web app with FakeMt5 seeded data.
# NOT a production path. For local dashboard testing only.
# Usage: uv run python -m metascan.web.dev_fake
from __future__ import annotations

import time

import uvicorn

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.web.composition import create_wired_app

BOT_MAGIC = 240101


def _seeded_fake() -> FakeMt5:
    fake = FakeMt5()
    fake.set_account(
        login=123456,
        balance=10_000.0,
        equity=10_050.0,
        margin=100.0,
        margin_free=9_900.0,
        margin_level=10050.0,
        currency="USD",
        trade_mode=0,
        margin_mode=2,
    )
    now_msc = int(time.time() * 1000)
    fake.add_symbol(
        "XAUUSDm",
        digits=2,
        point=0.01,
        trade_contract_size=100.0,
        trade_tick_size=0.01,
        trade_tick_value_loss=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_stops_level=0,
        trade_freeze_level=0,
        filling_mode=1,
        trade_mode=4,
        visible=True,
        select=True,
    )
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=now_msc)
    fake.set_positions([
        {
            "ticket": 1001,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.10,
            "price_open": 2300.00,
            "price_current": 2345.50,
            "sl": 2280.0,
            "tp": 2400.0,
            "profit": 45.50,
            "swap": -1.20,
            "type": 0,
            "time_msc": now_msc - 3_600_000,
        },
        {
            "ticket": 1002,
            "symbol": "XAUUSDm",
            "magic": 0,
            "volume": 0.05,
            "price_open": 2350.00,
            "price_current": 2345.50,
            "sl": 0.0,
            "tp": 0.0,
            "profit": -2.25,
            "swap": 0.0,
            "type": 1,
            "time_msc": now_msc - 1_800_000,
        },
        {
            "ticket": 1003,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.20,
            "price_open": 2310.00,
            "price_current": 2345.50,
            "sl": 2290.0,
            "tp": 0.0,
            "profit": 71.00,
            "swap": -0.50,
            "type": 0,
            "time_msc": now_msc - 7_200_000,
        },
    ])
    return fake


def main() -> None:
    fake = _seeded_fake()
    test_config = AppConfig(
        runtime=RuntimeConfig(
            runtime_name="XDirga Runtime V4",
            protocol_id="xdirga-runtime-v4",
            protocol_version="4.1.0",
            schema_version="1.1.0",
            broker_provider="EXNESS",
            broker_environment="TRIAL",
            execution_semantics="LIVE",
        ),
        credentials=Credentials(api_token="dev-token-not-secret"),
    )
    app = create_wired_app(
        mt5_module=fake,
        config=test_config,
        bot_magic=BOT_MAGIC,
        watchlist_bases=("XAUUSD",),
        symbol_suffix="m",
    )
    uvicorn.run(app, host="127.0.0.1", port=8787)


if __name__ == "__main__":
    main()
