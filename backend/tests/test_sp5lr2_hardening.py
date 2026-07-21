from __future__ import annotations

import asyncio
import json
import threading
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


def _seed(*, foreign: bool = False) -> FakeMt5:
    fake = FakeMt5()
    now_msc = int(time.time() * 1000)
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


def _refresh(fake: FakeMt5) -> None:
    fake.set_tick("XAUUSDm", bid=2345.50, ask=2345.80, time_msc=int(time.time() * 1000))


@asynccontextmanager
async def _client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def _wait_connected(client, fake: FakeMt5) -> dict:
    deadline = time.monotonic() + 8.0
    last = None
    while time.monotonic() < deadline:
        _refresh(fake)
        r = await client.get("/v4/snapshot", headers=AUTH)
        assert r.status_code == 200
        last = r.json()
        if last["snapshot"]["broker"]["connection"] == "CONNECTED":
            return last
        await asyncio.sleep(0.15)
    raise TimeoutError(f"not connected: {last}")


@pytest.mark.asyncio
async def test_sse_genuine_event_boot_coherent():
    # foreign magic → alert.created + connection events in journal
    # Use raw ASGI (httpx stream hangs on infinite SSE generators).
    fake = _seed(foreign=True)
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            deadline = time.monotonic() + 8.0
            snap_body = None
            while time.monotonic() < deadline:
                _refresh(fake)
                r = await client.get("/v4/snapshot", headers=AUTH)
                snap_body = r.json()
                if snap_body["metadata"]["sequence"] > 0:
                    break
                await asyncio.sleep(0.15)
            assert snap_body is not None
            assert snap_body["metadata"]["sequence"] > 0
            boot_id = snap_body["metadata"]["bootId"]
            snap_seq = snap_body["metadata"]["sequence"]

        qs = f"token={TOKEN}&bootId={boot_id}&sequence=0".encode()
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/v4/events/stream",
            "raw_path": b"/v4/events/stream",
            "query_string": qs,
            "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
        }
        recv_q: asyncio.Queue = asyncio.Queue()
        await recv_q.put({"type": "http.request", "body": b"", "more_body": False})
        sent: list = []

        async def _receive():
            return await recv_q.get()

        async def _send(msg):
            sent.append(msg)
            if msg["type"] == "http.response.body" and msg.get("body"):
                body = msg["body"]
                if b"event:" in body and b"system.resync" not in body:
                    await recv_q.put({"type": "http.disconnect"})

        try:
            await asyncio.wait_for(app(scope, _receive, _send), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass

        start = next((m for m in sent if m["type"] == "http.response.start"), None)
        assert start is not None
        assert start["status"] == 200
        bodies = b"".join(
            m.get("body", b"") for m in sent if m["type"] == "http.response.body"
        )
        text = bodies.decode("utf-8", errors="replace")
        assert "event:" in text, f"no SSE event frames: {text!r}"
        # extract first non-resync data payload
        got = False
        event_boot = None
        event_seq = None
        for block in text.split("\n\n"):
            if not block.strip() or block.startswith(":"):
                continue
            data_line = None
            for line in block.split("\n"):
                if line.startswith("data: "):
                    data_line = line[6:]
            if not data_line:
                continue
            try:
                payload = json.loads(data_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "system.resync.required":
                continue
            got = True
            event_boot = payload.get("bootId")
            event_seq = payload.get("sequence")
            break
        assert got, f"no genuine event in {text!r}"
        if event_boot is not None:
            assert event_boot == boot_id
        if event_seq is not None:
            assert isinstance(event_seq, int)
            assert event_seq >= 1
        assert snap_seq >= 1


def test_static_scan_full_web_dir_mutation_tokens():
    import metascan.web as web_pkg

    web_dir = Path(web_pkg.__file__).parent
    forbidden = [
        "order_check",
        ".mutation(",
        ".verify(",
        "sweep_facts",
        "submit_command",
        "order_send",
    ]
    allowlist: dict[str, set[str]] = {
        "commands.py": {"submit_command"},
    }
    violations = []
    for py_file in sorted(web_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        allowed = allowlist.get(py_file.name, set())
        for token in forbidden:
            if token not in content:
                continue
            if token in allowed:
                continue
            violations.append(f"{py_file.relative_to(web_dir)}: {token}")
    assert violations == [], f"mutation tokens found: {violations}"


@pytest.mark.asyncio
async def test_shutdown_no_thread_or_task_leak():
    before_threads = {t.name for t in threading.enumerate()}

    fake = _seed()
    app = create_wired_app(mt5_module=fake, config=_cfg(), bot_magic=BOT_MAGIC)
    async with _client(app) as client:
        await _wait_connected(client, fake)
        r = await client.get("/v4/snapshot", headers=AUTH)
        assert r.status_code == 200

    await asyncio.sleep(0.3)
    after_threads = {t.name for t in threading.enumerate()}
    leaked_threads = (after_threads - before_threads) & {"mt5-gateway"}
    assert not leaked_threads, f"gateway thread leaked: {leaked_threads}"
    # consumer task name should not remain among running tasks
    for t in asyncio.all_tasks():
        assert t.get_name() != "broker-state-consumer"
    assert "shutdown" in fake.call_log
