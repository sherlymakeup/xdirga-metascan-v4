from __future__ import annotations

import asyncio
import datetime
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import pytest

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.web.composition import create_wired_app
from metascan.web.routers.snapshot import _ownership

BOT_MAGIC = 240101
TOKEN = "FAKE-TEST-TOKEN-NOT-REAL"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
POS_MSC = 1_720_000_000_000 - 3_600_000


def _cfg() -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(
            runtime_name="XDirga Runtime V4",
            protocol_id="xdirga-runtime-v4",
            protocol_version="4.1.0",
            schema_version="1.1.0",
            broker_provider="EXNESS",
            broker_environment="TRIAL",
            execution_semantics="LIVE",
        ),
        credentials=Credentials(api_token=TOKEN),
    )


def _rich_fake() -> FakeMt5:
    fake = FakeMt5()
    fake.set_account(
        login=987654321,
        balance=25_000.50,
        equity=25_120.75,
        margin=250.0,
        margin_free=24_870.75,
        margin_level=10048.3,
        currency="USD",
        trade_mode=0,
        margin_mode=2,
    )
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
    now_msc = int(time.time() * 1000)
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=now_msc, last=2345.60)
    # All BOT_MAGIC so ALIEN_POSITION does not force permanent DEGRADED.
    # FOREIGN ownership is covered by a dedicated position with magic != bot via
    # separate seed in test_position_mapping_exact after wait, OR unit ownership test.
    # Use mixed magic: foreign is present → DEGRADED with ALIEN; mapping still works.
    fake.set_positions([
        {
            "ticket": 2001,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.15,
            "price_open": 2300.00,
            "price_current": 2345.50,
            "sl": 2280.0,
            "tp": 2400.0,
            "profit": 68.25,
            "swap": -0.50,
            "commission": -0.30,
            "type": 0,
            "time_msc": POS_MSC,
        },
        {
            "ticket": 2002,
            "symbol": "XAUUSDm",
            "magic": 0,
            "volume": 0.05,
            "price_open": 2360.00,
            "price_current": 2345.50,
            "sl": 0.0,
            "tp": 0.0,
            "profit": -7.25,
            "swap": 0.0,
            "commission": 0.0,
            "type": 1,
            "time_msc": POS_MSC,
        },
        {
            "ticket": 2003,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.20,
            "price_open": 2310.00,
            "price_current": 2345.50,
            "sl": 2290.0,
            "tp": 0.0,
            "profit": 71.00,
            "swap": -0.10,
            "commission": 0.0,
            "type": 0,
            "time_msc": POS_MSC,
        },
        {
            "ticket": 2004,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.01,
            "price_open": 2340.00,
            "price_current": 2345.50,
            "sl": 0.0,
            "tp": 2360.0,
            "profit": 0.55,
            "swap": 0.0,
            "commission": 0.0,
            "type": 0,
            "time_msc": POS_MSC,
        },
    ])
    return fake


def _refresh(fake: FakeMt5) -> None:
    fake.set_tick(
        "XAUUSDm",
        bid=2345.50,
        ask=2345.80,
        time_msc=int(time.time() * 1000),
        last=2345.60,
    )


@asynccontextmanager
async def _client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def _wait_data(client, fake: FakeMt5) -> dict:
    deadline = time.monotonic() + 8.0
    last = None
    while time.monotonic() < deadline:
        _refresh(fake)
        r = await client.get("/v4/snapshot", headers=AUTH)
        assert r.status_code == 200
        last = r.json()
        if (
            last["snapshot"]["accountAvailable"] is True
            and last["snapshot"]["positionsAvailable"] is True
            and len(last["snapshot"]["positions"]) == 4
        ):
            return last
        await asyncio.sleep(0.15)
    raise TimeoutError(f"not ready: {last}")


@pytest.mark.asyncio
async def test_account_row_to_wire_exact():
    fake = _rich_fake()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        body = await _wait_data(client, fake)
    acc = body["snapshot"]["account"]
    broker = body["snapshot"]["broker"]
    assert acc["currency"] == "USD"
    assert acc["balance"] == 25_000.50
    assert acc["equity"] == 25_120.75
    assert acc["margin"] == 250.0
    assert acc["freeMargin"] == 24_870.75
    assert acc["marginLevel"] == 10048.3
    assert acc["freshness"] == "STALE"
    assert acc["realizedPnlToday"] is None
    assert broker["loginMasked"] == "***"
    assert "987654321" not in str(body)


@pytest.mark.asyncio
async def test_position_mapping_exact():
    fake = _rich_fake()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        body = await _wait_data(client, fake)
    by_t = {p["brokerTicket"]: p for p in body["snapshot"]["positions"]}

    p1 = by_t["2001"]
    assert p1["ownership"] == "BOT_MANAGED"
    assert p1["side"] == "BUY"
    assert p1["volume"] == 0.15
    assert p1["entryPrice"] == 2300.00
    assert p1["currentPrice"] == 2345.50
    assert p1["stopLoss"] == 2280.0
    assert p1["takeProfit"] == 2400.0
    assert p1["floatingPnl"] == 68.25
    assert p1["swap"] == -0.50
    assert p1["commission"] == -0.30
    assert p1["netPnl"] == pytest.approx(68.25 + -0.50 + -0.30)
    assert p1["protection"] == "PROTECTED"
    assert p1["realizedPnl"] is None
    assert p1["riskAmount"] is None
    assert p1["riskPct"] is None
    assert p1["rMultiple"] is None
    assert p1["mfe"] is None
    assert p1["mae"] is None
    expected_iso = (
        datetime.datetime.fromtimestamp(POS_MSC / 1000, datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    assert p1["openedAt"] == expected_iso

    p2 = by_t["2002"]
    assert p2["ownership"] == "FOREIGN"
    assert p2["side"] == "SELL"
    assert p2["stopLoss"] is None
    assert p2["takeProfit"] is None
    assert p2["protection"] == "UNPROTECTED"

    p3 = by_t["2003"]
    assert p3["ownership"] == "BOT_MANAGED"
    assert p3["stopLoss"] == 2290.0
    assert p3["takeProfit"] is None
    assert p3["protection"] == "PARTIALLY_PROTECTED"

    p4 = by_t["2004"]
    assert p4["stopLoss"] is None
    assert p4["takeProfit"] == 2360.0
    assert p4["protection"] == "PARTIALLY_PROTECTED"


def test_ownership_unknown_path_exists():
    assert _ownership(magic=1, bot_magic=None) == "UNKNOWN"
    assert _ownership(magic=BOT_MAGIC, bot_magic=BOT_MAGIC) == "BOT_MANAGED"
    assert _ownership(magic=0, bot_magic=BOT_MAGIC) == "FOREIGN"


@pytest.mark.asyncio
async def test_tick_mapping_and_freshness():
    # BOT-only positions so connection can be CONNECTED (no ALIEN permanent DEGRADED)
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
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=int(time.time() * 1000), last=2345.60)
    fake.set_positions([
        {
            "ticket": 2001,
            "symbol": "XAUUSDm",
            "magic": BOT_MAGIC,
            "volume": 0.15,
            "price_open": 2300.00,
            "price_current": 2345.50,
            "sl": 2280.0,
            "tp": 2400.0,
            "profit": 68.25,
            "swap": -0.50,
            "commission": -0.30,
            "type": 0,
            "time_msc": POS_MSC,
        },
    ])
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        deadline = time.monotonic() + 8.0
        body = None
        while time.monotonic() < deadline:
            _refresh(fake)
            r = await client.get("/v4/snapshot", headers=AUTH)
            body = r.json()
            if (
                body["snapshot"]["broker"]["connection"] == "CONNECTED"
                and body["snapshot"]["markets"]
            ):
                break
            await asyncio.sleep(0.15)
        assert body is not None
        assert body["snapshot"]["broker"]["connection"] == "CONNECTED"
        m = body["snapshot"]["markets"][0]
        assert m["symbol"] == "XAUUSDm"
        assert m["bid"] == 2345.50
        assert m["ask"] == 2345.80
        assert m["spread"] == pytest.approx(0.30)
        assert m["last"] == 2345.60
        assert m["contractSize"] == 100.0
        assert m["tickSize"] == 0.01
        assert m["minVolume"] == 0.01
        assert m["maxVolume"] == 100.0
        assert m["volumeStep"] == 0.01
        assert m["freshness"] == "FRESH"
        assert m["swapLong"] is None
        assert m["changePct"] is None


@pytest.mark.asyncio
async def test_derived_null_fields_regression():
    fake = _rich_fake()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        body = await _wait_data(client, fake)
    snap = body["snapshot"]
    for p in snap["positions"]:
        assert p["realizedPnl"] is None
        assert p["riskAmount"] is None
        assert p["riskPct"] is None
        assert p["rMultiple"] is None
        assert p["mfe"] is None
        assert p["mae"] is None
        assert p["strategy"] is None
        assert p["management"] is None
    acc = snap["account"]
    for k in (
        "realizedPnlToday",
        "realizedPnlWeek",
        "dailyDrawdown",
        "maxDrawdown",
        "grossExposure",
        "netExposure",
        "pendingOrders",
        "tradesToday",
        "winRate",
        "profitFactor",
        "riskUtilization",
    ):
        assert acc[k] is None, k
