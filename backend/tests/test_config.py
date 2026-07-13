"""Config loading: config.toml + credential-only .env; reject demo/mock/paper."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from metascan.config import ConfigError, load_config


def test_loads_config_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            """
            [runtime]
            runtime_name = "XDirga Runtime V4"
            protocol_id = "xdirga-runtime-v4"
            protocol_version = "4.1.0"
            schema_version = "1.1.0"
            broker_provider = "EXNESS"
            broker_environment = "TRIAL"
            execution_semantics = "LIVE"
            symbol_suffix = "m"
            bot_magic = 1
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = load_config(config_path=cfg, env_path=None)
    assert loaded.runtime.protocol_version == "4.1.0"
    assert loaded.runtime.execution_semantics == "LIVE"


def test_env_loads_credentials_only(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            """
            [runtime]
            runtime_name = "XDirga Runtime V4"
            protocol_id = "xdirga-runtime-v4"
            protocol_version = "4.1.0"
            schema_version = "1.1.0"
            broker_provider = "EXNESS"
            broker_environment = "TRIAL"
            execution_semantics = "LIVE"
            symbol_suffix = "m"
            bot_magic = 1
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    # FAKE fixture — never a real account.
    env.write_text(
        "MT5_LOGIN=123456\nMT5_PASSWORD=FAKE-TEST-PASSWORD-NOT-REAL\nMT5_SERVER=Exness-Trial\nAPI_TOKEN=FAKE-TEST-TOKEN-NOT-REAL\n",
        encoding="utf-8",
    )
    loaded = load_config(config_path=cfg, env_path=env)
    assert loaded.credentials.mt5_login == "123456"
    assert loaded.credentials.mt5_password == "FAKE-TEST-PASSWORD-NOT-REAL"
    assert loaded.credentials.mt5_server == "Exness-Trial"
    assert loaded.credentials.api_token == "FAKE-TEST-TOKEN-NOT-REAL"


@pytest.mark.parametrize(
    "flag_line",
    [
        "DEMO_MODE=1",
        "MOCK_MODE=true",
        "PAPER_TRADING=yes",
        "RUNTIME_MODE=demo",
        "TRADING_MODE=paper",
        "USE_MOCK=1",
    ],
)
def test_rejects_demo_mock_paper_runtime_flags(tmp_path: Path, flag_line: str) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            """
            [runtime]
            runtime_name = "XDirga Runtime V4"
            protocol_id = "xdirga-runtime-v4"
            protocol_version = "4.1.0"
            schema_version = "1.1.0"
            broker_provider = "EXNESS"
            broker_environment = "TRIAL"
            execution_semantics = "LIVE"
            symbol_suffix = "m"
            bot_magic = 1
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    env.write_text(
        f"MT5_LOGIN=1\nMT5_PASSWORD=x\nMT5_SERVER=s\nAPI_TOKEN=t\n{flag_line}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="demo|mock|paper"):
        load_config(config_path=cfg, env_path=env)


def test_rejects_forbidden_keys_in_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            """
            [runtime]
            runtime_name = "XDirga Runtime V4"
            protocol_id = "xdirga-runtime-v4"
            protocol_version = "4.1.0"
            schema_version = "1.1.0"
            broker_provider = "EXNESS"
            broker_environment = "TRIAL"
            execution_semantics = "LIVE"
            symbol_suffix = "m"
            bot_magic = 1
            demo_mode = true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="demo|mock|paper"):
        load_config(config_path=cfg, env_path=None)


_MIN_RUNTIME = textwrap.dedent(
    """
    [runtime]
    runtime_name = "XDirga Runtime V4"
    protocol_id = "xdirga-runtime-v4"
    protocol_version = "4.1.0"
    schema_version = "1.1.0"
    broker_provider = "EXNESS"
    broker_environment = "TRIAL"
    execution_semantics = "LIVE"
    symbol_suffix = "m"
    bot_magic = 1
    """
).strip()


@pytest.mark.parametrize(
    "override_line",
    [
        'execution_semantics = "demo"',
        'execution_semantics = "mock"',
        'execution_semantics = "paper"',
        'execution_semantics = "fixture"',
        'execution_semantics = "simulation"',
        'broker_environment = "demo"',
        'trading_mode = "paper"',
        'mode = "mock"',
    ],
)
def test_rejects_forbidden_scalar_values_regardless_of_key(
    tmp_path: Path, override_line: str
) -> None:
    """Forbidden mode tokens as TOML scalar values are rejected even on innocuous keys."""
    cfg = tmp_path / "config.toml"
    # Replace LIVE line when override targets execution_semantics; else append.
    body = _MIN_RUNTIME
    key = override_line.split("=", 1)[0].strip()
    if f"{key} =" in body or f"{key}=" in body.replace(" ", ""):
        # swap existing key assignment
        lines = []
        for line in body.splitlines():
            if line.strip().startswith(f"{key} "):
                lines.append(override_line)
            else:
                lines.append(line)
        body = "\n".join(lines)
    else:
        body = body + "\n" + override_line
    cfg.write_text(body + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="demo|mock|paper|fixture|simulation"):
        load_config(config_path=cfg, env_path=None)


def test_allows_normal_strings_that_are_not_mode_tokens(tmp_path: Path) -> None:
    """Paths/names containing substrings must not false-positive."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        _MIN_RUNTIME
        + "\n"
        + textwrap.dedent(
            """
            [paths]
            data_dir = "data/demo-notes-archive"
            journal_db = "C:/Users/paperplane/metascan/journal.sqlite"
            label = "myfixture-helper"
            """
        ),
        encoding="utf-8",
    )
    loaded = load_config(config_path=cfg, env_path=None)
    assert loaded.runtime.execution_semantics == "LIVE"


def test_loads_shipped_config_toml_with_temp_credentials() -> None:
    """Shipped backend/config.toml must load (nested symbols) with credential-only env."""
    import tempfile

    backend = Path(__file__).resolve().parents[1]
    shipped = backend / "config.toml"
    assert shipped.is_file()
    with tempfile.TemporaryDirectory() as td:
        env = Path(td) / ".env"
        env.write_text(
            "MT5_LOGIN=testlogin\nMT5_PASSWORD=testpass\n"
            "MT5_SERVER=Exness-Trial\nAPI_TOKEN=testtoken\n",
            encoding="utf-8",
        )
        loaded = load_config(config_path=shipped, env_path=env)
    assert loaded.runtime.protocol_version == "4.1.0"
    assert loaded.runtime.execution_semantics == "LIVE"
    assert loaded.runtime.symbols is not None
    assert "XAUUSD" in loaded.runtime.symbols.watchlist
    assert loaded.credentials.mt5_login == "testlogin"


def test_default_env_path_adjacent_to_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_MIN_RUNTIME + "\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "MT5_LOGIN=adj\nMT5_PASSWORD=p\nMT5_SERVER=s\nAPI_TOKEN=t\n",
        encoding="utf-8",
    )
    loaded = load_config(config_path=cfg)  # env_path omitted → adjacent .env
    assert loaded.credentials.mt5_login == "adj"
