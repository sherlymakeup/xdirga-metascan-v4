from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

import httpx
import pytest

from metascan.config import AppConfig, Credentials, RuntimeConfig
from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.web.composition import create_wired_app

BOT_MAGIC = 240101
TOKEN = "FAKE-TEST-TOKEN-NOT-REAL"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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


def _seed(*, foreign: bool = False, tick_msc: int | None = None) -> FakeMt5:
    fake = FakeMt5()
    now_msc = tick_msc if tick_msc is not None else int(time.time() * 1000)
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
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=now_msc)
    rows = [
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
    ]
    if foreign:
        rows.append(
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
            }
        )
    fake.set_positions(rows)
    return fake


def _refresh_tick(fake: FakeMt5) -> None:
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=int(time.time() * 1000))


@asynccontextmanager
async def _client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def _wait_snap(
    client,
    pred: Callable[[dict], bool],
    *,
    fake: FakeMt5 | None = None,
    timeout: float = 8.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if fake is not None:
            _refresh_tick(fake)
        r = await client.get("/v4/snapshot", headers=AUTH)
        assert r.status_code == 200
        last = r.json()
        if pred(last):
            return last
        await asyncio.sleep(0.15)
    raise TimeoutError(f"predicate not met; last={last}")


@pytest.mark.asyncio
async def test_runtime_fail_to_disconnected_truthful():
    fake = _seed()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        await _wait_snap(
            client,
            lambda b: b["snapshot"]["broker"]["connection"] == "CONNECTED"
            and b["snapshot"]["accountAvailable"] is True,
            fake=fake,
        )
        fake.fail_next("positions_get", times=8)
        body = await _wait_snap(
            client,
            lambda b: b["snapshot"]["broker"]["connection"] in {"DEGRADED", "DISCONNECTED"},
            timeout=10.0,
        )
        snap = body["snapshot"]
        assert snap["runtime"]["state"] != "READY"
        assert snap["runtime"]["stateReason"] in {"MT5_DEGRADED", "MT5_DISCONNECTED"}
        if snap["accountAvailable"] is False:
            assert snap["account"]["freshness"] in {"STALE", "UNAVAILABLE"}
        assert snap["runtime"]["state"] != "READY"


@pytest.mark.asyncio
async def test_boot_fail_initialize():
    fake = _seed()
    fake.fail_next("initialize")
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        r = await client.get("/v4/snapshot", headers=AUTH)
    assert r.status_code == 200
    snap = r.json()["snapshot"]
    assert snap["accountAvailable"] is False
    assert snap["runtime"]["stateReason"] == "SP4_NO_MT5"
    assert snap["account"]["balance"] is None


@pytest.mark.asyncio
async def test_boot_fail_account_info():
    fake = _seed()
    fake.fail_next("account_info")
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        r = await client.get("/v4/snapshot", headers=AUTH)
    assert r.status_code == 200
    snap = r.json()["snapshot"]
    assert snap["accountAvailable"] is False
    assert snap["runtime"]["stateReason"] == "SP4_NO_MT5"
    assert snap["positions"] == []


@pytest.mark.asyncio
async def test_positions_get_error_no_ghost_fresh():
    fake = _seed()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        await _wait_snap(
            client,
            lambda b: len(b["snapshot"]["positions"]) == 1
            and b["snapshot"]["positionsAvailable"] is True,
            fake=fake,
        )
        fake.fail_next("positions_get", times=3)
        body = await _wait_snap(
            client,
            lambda b: b["snapshot"]["positionsAvailable"] is False
            or b["snapshot"]["broker"]["connection"] != "CONNECTED",
            timeout=6.0,
        )
        snap = body["snapshot"]
        assert snap["positionsAvailable"] is False or snap["broker"]["connection"] != "CONNECTED"
        if snap["positions"]:
            for p in snap["positions"]:
                assert p["dataAvailable"] is False or snap["positionsAvailable"] is False
        assert snap["runtime"]["stateReason"].startswith("MT5_")


@pytest.mark.asyncio
async def test_tick_stale_freshness():
    old_msc = int(time.time() * 1000) - 10_000
    fake = _seed(tick_msc=old_msc)
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        # do NOT refresh tick — want wall-age STALE
        body = await _wait_snap(
            client,
            lambda b: len(b["snapshot"]["markets"]) >= 1,
        )
        m = body["snapshot"]["markets"][0]
        assert m["symbol"] == "XAUUSDm"
        assert m["freshness"] == "STALE"
        assert m["tickAgeMs"] > 1000.0
        if body["snapshot"]["accountAvailable"]:
            assert body["snapshot"]["account"]["balance"] == 10_000.0


@pytest.mark.asyncio
async def test_recovery_without_restart():
    fake = _seed()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        await _wait_snap(
            client,
            lambda b: b["snapshot"]["broker"]["connection"] == "CONNECTED",
            fake=fake,
        )
        fake.fail_next("positions_get", times=8)
        await _wait_snap(
            client,
            lambda b: b["snapshot"]["broker"]["connection"] in {"DEGRADED", "DISCONNECTED"},
            timeout=10.0,
        )
        body = await _wait_snap(
            client,
            lambda b: b["snapshot"]["broker"]["connection"] == "CONNECTED"
            and b["snapshot"]["accountAvailable"] is True
            and b["snapshot"]["positionsAvailable"] is True,
            fake=fake,
            timeout=12.0,
        )
        assert body["snapshot"]["runtime"]["state"] == "READY"
        assert body["snapshot"]["runtime"]["stateReason"] == "MT5_CONNECTED"


@pytest.mark.asyncio
async def test_boot_lineage_stable_then_changes():
    fake = _seed()
    app1 = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app1) as client:
        await _wait_snap(
            client,
            lambda b: b["snapshot"]["accountAvailable"] is True,
            fake=fake,
        )
        r1 = await client.get("/v4/snapshot", headers=AUTH)
        r2 = await client.get("/v4/snapshot", headers=AUTH)
        m1, m2 = r1.json()["metadata"], r2.json()["metadata"]
        assert m1["bootId"] == m2["bootId"]
        assert m2["sequence"] >= m1["sequence"]
        boot1 = m1["bootId"]

    fake2 = _seed()
    app2 = create_wired_app(mt5_module=fake2, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app2) as client:
        await _wait_snap(
            client,
            lambda b: b["snapshot"]["accountAvailable"] is True,
            fake=fake2,
        )
        r3 = await client.get("/v4/snapshot", headers=AUTH)
        boot2 = r3.json()["metadata"]["bootId"]
    assert boot2 != boot1
