from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.web.composition import create_wired_app

BOT_MAGIC = 240101
TOKEN = "FAKE-TEST-TOKEN-NOT-REAL"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _test_config() -> AppConfig:
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


@asynccontextmanager
async def _wired_client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    lifespan = app.router.lifespan_context
    async with lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ---------- a) End-to-end: wired app with seeded FakeMt5 ----------

@pytest.mark.asyncio
async def test_e2e_snapshot_returns_seeded_data():
    app = create_wired_app(
        mt5_module=_seeded_fake(),
        config=_test_config(),
        bot_magic=BOT_MAGIC,
    )
    async with _wired_client(app) as client:
        await asyncio.sleep(0.3)
        resp = await client.get("/v4/snapshot", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    snap = body["snapshot"]
    meta = body["metadata"]

    assert snap["accountAvailable"] is True
    assert snap["account"]["balance"] == 10_000.0
    assert snap["account"]["equity"] == 10_050.0
    assert snap["account"]["currency"] == "USD"

    assert len(snap["positions"]) == 3

    by_ticket = {p["brokerTicket"]: p for p in snap["positions"]}
    p1 = by_ticket["1001"]
    assert p1["ownership"] == "BOT_MANAGED"
    assert p1["volume"] == 0.10
    assert p1["entryPrice"] == 2300.00
    assert p1["floatingPnl"] == 45.50
    assert p1["side"] == "BUY"
    assert p1["stopLoss"] == 2280.0
    assert p1["takeProfit"] == 2400.0
    assert p1["protection"] == "PROTECTED"

    p2 = by_ticket["1002"]
    assert p2["ownership"] == "FOREIGN"
    assert p2["side"] == "SELL"
    assert p2["volume"] == 0.05
    assert p2["floatingPnl"] == -2.25
    assert p2["protection"] == "UNPROTECTED"

    p3 = by_ticket["1003"]
    assert p3["ownership"] == "BOT_MANAGED"
    assert p3["protection"] == "PARTIALLY_PROTECTED"

    assert len(snap["markets"]) >= 1
    market = snap["markets"][0]
    assert market["symbol"] == "XAUUSDm"
    assert market["bid"] == 2345.50
    assert market["ask"] == 2345.80

    assert meta["bootId"] is not None
    assert meta["schemaHash"] is not None


# ---------- b) SSE/stream coherence ----------

@pytest.mark.asyncio
async def test_snapshot_boot_id_sequence_coherent():
    app = create_wired_app(
        mt5_module=_seeded_fake(),
        config=_test_config(),
        bot_magic=BOT_MAGIC,
    )
    async with _wired_client(app) as client:
        await asyncio.sleep(0.3)
        r1 = await client.get("/v4/snapshot", headers=AUTH)
        r2 = await client.get("/v4/snapshot", headers=AUTH)

    m1 = r1.json()["metadata"]
    m2 = r2.json()["metadata"]
    assert m1["bootId"] == m2["bootId"]
    assert m2["sequence"] >= m1["sequence"]


# ---------- c) Fallback: no module, no env → SP4 unavailable ----------

@pytest.mark.asyncio
async def test_fallback_no_module_sp4_behavior(monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.delenv("MT5_PASSWORD", raising=False)
    monkeypatch.delenv("MT5_SERVER", raising=False)

    app = create_wired_app(config=_test_config())
    async with _wired_client(app) as client:
        resp = await client.get("/v4/snapshot", headers=AUTH)

    assert resp.status_code == 200
    snap = resp.json()["snapshot"]
    assert snap["accountAvailable"] is False
    assert snap["runtime"]["stateReason"] == "SP4_NO_MT5"
    assert snap["broker"]["connection"] == "DISCONNECTED"
    assert snap["positions"] == []
    assert snap["account"]["balance"] is None


# ---------- d) Boot failure: app alive, snapshot unavailable ----------

@pytest.mark.asyncio
async def test_boot_failure_app_survives():
    fake = _seeded_fake()
    fake.fail_next("initialize")
    app = create_wired_app(
        mt5_module=fake,
        config=_test_config(),
        bot_magic=BOT_MAGIC,
    )
    async with _wired_client(app) as client:
        resp = await client.get("/v4/snapshot", headers=AUTH)

    assert resp.status_code == 200
    snap = resp.json()["snapshot"]
    assert snap["accountAvailable"] is False
    assert snap["runtime"]["stateReason"] == "SP4_NO_MT5"


# ---------- e) Seam mutasi unreachable ----------

@pytest.mark.asyncio
async def test_gateway_not_on_app_state():
    app = create_wired_app(
        mt5_module=_seeded_fake(),
        config=_test_config(),
        bot_magic=BOT_MAGIC,
    )
    async with _wired_client(app) as client:
        await asyncio.sleep(0.1)
        await client.get("/v4/snapshot", headers=AUTH)
    assert not hasattr(app.state, "gateway")


def test_static_scan_no_mutation_tokens():
    import metascan.web as web_pkg
    web_dir = Path(web_pkg.__file__).parent
    forbidden = {"order_check", ".mutation(", ".verify(", "sweep_facts", "submit_command", "order_send"}
    scan_files = {"composition.py", "dev_fake.py", "dependencies.py"}
    violations = []
    for py_file in web_dir.rglob("*.py"):
        if py_file.name not in scan_files:
            continue
        content = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            if token in content:
                violations.append(f"{py_file.name}: {token}")
    assert violations == [], f"mutation tokens found: {violations}"


# ---------- f) Shutdown clean ----------

@pytest.mark.asyncio
async def test_shutdown_clean():
    fake = _seeded_fake()
    app = create_wired_app(
        mt5_module=fake,
        config=_test_config(),
        bot_magic=BOT_MAGIC,
    )
    async with _wired_client(app) as client:
        await asyncio.sleep(0.3)
        resp = await client.get("/v4/snapshot", headers=AUTH)
        assert resp.status_code == 200

    assert "shutdown" in fake.call_log
