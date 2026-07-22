from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from metascan.mt5.testing.fake_mt5 import FakeMt5
from metascan.web.live_read import build_live_app

TOKEN = "TEST-TOKEN-NOT-SECRET"
BOT_MAGIC = 240101


@pytest.fixture(scope="module", autouse=True)
def _no_journal_temp_delta():
    temp_dir = Path(tempfile.gettempdir())
    before = set(temp_dir.glob("metascan-journal-*"))
    yield
    after = set(temp_dir.glob("metascan-journal-*"))
    leaked = after - before
    assert not leaked, f"journal temp delta {len(leaked)}: {sorted(leaked)}"


async def _run_lifespan(app) -> None:
    async with app.router.lifespan_context(app):
        pass


def _write_config(
    tmp_path: Path,
    *,
    api_token: str = TOKEN,
    mt5_login: str = "",
    mt5_password: str = "",
    mt5_server: str = "",
) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[runtime]
runtime_name = "XDirga Runtime V4"
protocol_id = "xdirga-runtime-v4"
protocol_version = "4.1.0"
schema_version = "1.1.0"
broker_provider = "EXNESS"
broker_environment = "TRIAL"
execution_semantics = "LIVE"
symbol_suffix = "m"
bot_magic = 240101

[runtime.symbols]
watchlist = ["XAUUSD"]
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"MT5_LOGIN={mt5_login}\n"
        f"MT5_PASSWORD={mt5_password}\n"
        f"MT5_SERVER={mt5_server}\n"
        f"API_TOKEN={api_token}\n",
        encoding="utf-8",
    )
    return config_path


def _set_mt5_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_LOGIN", "LOGIN-SENTINEL")
    monkeypatch.setenv("MT5_PASSWORD", "PASSWORD-SENTINEL")
    monkeypatch.setenv("MT5_SERVER", "SERVER-SENTINEL")


def _seed() -> FakeMt5:
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
    fake.set_tick("XAUUSDm", bid=2345.5, ask=2345.8, time_msc=now_msc)
    fake.set_positions(
        [
            {
                "ticket": 1001,
                "symbol": "XAUUSDm",
                "magic": BOT_MAGIC,
                "volume": 0.1,
                "price_open": 2300.0,
                "price_current": 2345.5,
                "sl": 2280.0,
                "tp": 2400.0,
                "profit": 45.5,
                "swap": -1.2,
                "type": 0,
                "time_msc": now_msc - 1000,
            },
            {
                "ticket": 1002,
                "symbol": "XAUUSDm",
                "magic": 0,
                "volume": 0.1,
                "price_open": 2300.0,
                "price_current": 2345.5,
                "sl": 0.0,
                "tp": 0.0,
                "profit": 0.0,
                "swap": 0.0,
                "type": 1,
                "time_msc": now_msc - 1000,
            },
        ]
    )
    return fake


def test_empty_api_token_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = _write_config(tmp_path, api_token="")
    _set_mt5_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        build_live_app(config_path=config_path, mt5_module=FakeMt5())

    assert exc.value.code != 0
    assert "API_TOKEN" in str(exc.value)
    assert str(tmp_path / ".env") in str(exc.value)


def test_env_file_credentials_bridge_without_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    values = {
        "MT5_LOGIN": "FILE-LOGIN-SENTINEL",
        "MT5_PASSWORD": "FILE-PASSWORD-SENTINEL",
        "MT5_SERVER": "FILE-SERVER-SENTINEL",
    }
    config_path = _write_config(
        tmp_path,
        mt5_login=values["MT5_LOGIN"],
        mt5_password=values["MT5_PASSWORD"],
        mt5_server=values["MT5_SERVER"],
    )
    for name in values:
        monkeypatch.delenv(name, raising=False)

    app = build_live_app(config_path=config_path, mt5_module=FakeMt5())

    assert app is not None
    asyncio.run(_run_lifespan(app))
    for name, value in values.items():
        assert os.environ[name] == value
        assert value not in caplog.text


def test_process_env_wins_over_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = _write_config(
        tmp_path,
        mt5_login="FILE-LOGIN-SENTINEL",
        mt5_password="FILE-PASSWORD-SENTINEL",
        mt5_server="FILE-SERVER-SENTINEL",
    )
    process_values = {
        "MT5_LOGIN": "PROCESS-LOGIN-SENTINEL",
        "MT5_PASSWORD": "PROCESS-PASSWORD-SENTINEL",
        "MT5_SERVER": "PROCESS-SERVER-SENTINEL",
    }
    for name, value in process_values.items():
        monkeypatch.setenv(name, value)

    app = build_live_app(config_path=config_path, mt5_module=FakeMt5())
    asyncio.run(_run_lifespan(app))

    for name, value in process_values.items():
        assert os.environ[name] == value


def test_missing_mt5_env_names_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("MT5_LOGIN", "LOGIN-SENTINEL")
    monkeypatch.setenv("MT5_PASSWORD", "PASSWORD-SENTINEL")
    monkeypatch.delenv("MT5_SERVER", raising=False)

    with pytest.raises(SystemExit) as exc:
        build_live_app(config_path=config_path, mt5_module=FakeMt5())

    output = f"{exc.value} {caplog.text}"
    assert exc.value.code != 0
    assert "MT5_SERVER" in output
    assert "backend/.env.example" in output
    assert f"isi {tmp_path / '.env'}" in output
    assert "LOGIN-SENTINEL" not in output
    assert "PASSWORD-SENTINEL" not in output


def test_missing_config_exits_nonzero(tmp_path: Path):
    missing = tmp_path / "missing.toml"

    with pytest.raises(SystemExit) as exc:
        build_live_app(config_path=missing, mt5_module=FakeMt5())

    assert exc.value.code != 0
    assert "config" in str(exc.value).lower()
    assert "not found" in str(exc.value).lower()


def test_missing_mt5_module_exits_with_install_instruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = _write_config(tmp_path)
    _set_mt5_env(monkeypatch)

    def reject_mt5_import(name: str):
        assert name == "MetaTrader5"
        raise ImportError("not installed")

    monkeypatch.setattr(
        "metascan.web.live_read.importlib.import_module", reject_mt5_import
    )

    with pytest.raises(SystemExit) as exc:
        build_live_app(config_path=config_path)

    assert exc.value.code != 0
    assert "MetaTrader5" in str(exc.value)
    assert "install" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_injected_live_app_auth_and_configured_magic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    config_path = _write_config(tmp_path)
    _set_mt5_env(monkeypatch)
    app = build_live_app(config_path=config_path, mt5_module=_seed())

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = None
            for _ in range(40):
                response = await client.get(
                    "/v4/snapshot", headers={"Authorization": f"Bearer {TOKEN}"}
                )
                body = response.json()
                if body["snapshot"]["positions"]:
                    break
                await asyncio.sleep(0.1)
            wrong = await client.get(
                "/v4/snapshot", headers={"Authorization": "Bearer wrong"}
            )
            missing = await client.get("/v4/snapshot")

    assert response.status_code == 200
    assert body is not None
    ownership = {p["brokerTicket"]: p["ownership"] for p in body["snapshot"]["positions"]}
    assert ownership == {"1001": "BOT_MANAGED", "1002": "FOREIGN"}
    assert wrong.status_code == 401
    assert missing.status_code == 401
    for value in ("LOGIN-SENTINEL", "PASSWORD-SENTINEL", "SERVER-SENTINEL"):
        assert value not in caplog.text
