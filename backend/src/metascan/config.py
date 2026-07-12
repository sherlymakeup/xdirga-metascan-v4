"""config.toml + credential-only .env; reject demo/mock/paper runtime flags."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer


# Forbidden tokens as whole scalar values (not substrings of paths/names).
_FORBIDDEN_VALUE_TOKENS = frozenset(
    {"demo", "mock", "paper", "fixture", "simulation"}
)

# Forbidden substrings in keys (flags like demo_mode, use_mock).
_FORBIDDEN_KEY = re.compile(r"(demo|mock|paper|fixture|simulation)", re.IGNORECASE)

_ENV_CREDENTIAL_KEYS = frozenset(
    {
        "MT5_LOGIN",
        "MT5_PASSWORD",
        "MT5_SERVER",
        "API_TOKEN",
    }
)

_MODE_FLAG_KEYS = re.compile(
    r"(DEMO|MOCK|PAPER|FIXTURE|SIMULATION|RUNTIME_MODE|TRADING_MODE|USE_MOCK|PAPER_TRADING|DEMO_MODE|MOCK_MODE)",
    re.IGNORECASE,
)


class ConfigError(ValueError):
    pass


class Credentials(BaseModel):
    """Credential bag: real values for app use; never in repr/str/model_dump."""

    model_config = ConfigDict(extra="forbid")

    mt5_login: str = ""
    mt5_password: str = ""
    mt5_server: str = ""
    api_token: str = ""

    def __repr__(self) -> str:
        return "Credentials(mt5_login=***, mt5_password=***, mt5_server=***, api_token=***)"

    def __str__(self) -> str:
        return self.__repr__()

    @model_serializer(mode="wrap")
    def _serialize(self, handler):  # type: ignore[no-untyped-def]
        data = handler(self)
        return {k: "***" for k in data}


class RuntimeSymbols(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist: list[str] = Field(default_factory=list)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str
    protocol_id: str
    protocol_version: str
    schema_version: str
    broker_provider: str
    broker_environment: str
    execution_semantics: str
    symbol_suffix: str = "m"
    bot_magic: int = 0
    symbols: RuntimeSymbols | None = None


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    runtime: RuntimeConfig
    credentials: Credentials = Field(default_factory=Credentials)


def _is_forbidden_scalar(value: Any) -> bool:
    """True when value is exactly a forbidden mode token (not a path substring)."""
    if not isinstance(value, str):
        return False
    return value.strip().casefold() in _FORBIDDEN_VALUE_TOKENS


def _scan_forbidden(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_path = f"{path}.{k}" if path else str(k)
            if _FORBIDDEN_KEY.search(str(k)):
                raise ConfigError(f"forbidden demo/mock/paper key: {key_path}")
            if _is_forbidden_scalar(v):
                raise ConfigError(
                    f"forbidden demo/mock/paper/fixture/simulation value at {key_path}"
                )
            _scan_forbidden(v, key_path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            item_path = f"{path}[{i}]"
            if _is_forbidden_scalar(v):
                raise ConfigError(
                    f"forbidden demo/mock/paper/fixture/simulation value at {item_path}"
                )
            _scan_forbidden(v, item_path)


def _parse_env(path: Path) -> dict[str, str]:
    raw: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        raw[k.strip()] = v.strip().strip('"').strip("'")
    return raw


def _reject_env_flags(env: dict[str, str]) -> None:
    for k, v in env.items():
        if k in _ENV_CREDENTIAL_KEYS:
            continue
        if (
            _MODE_FLAG_KEYS.search(k)
            or _FORBIDDEN_KEY.search(k)
            or _is_forbidden_scalar(v)
        ):
            raise ConfigError(f"forbidden demo/mock/paper env: {k}")


def load_config(
    *,
    config_path: Path | str | None = None,
    env_path: Path | str | None = None,
) -> AppConfig:
    if config_path is None:
        config_path = Path("config.toml")
    config_path = Path(config_path)
    if not config_path.is_file():
        raise ConfigError(f"config not found: {config_path}")

    # Default: credential-only .env adjacent to config.toml
    if env_path is None:
        env_path = config_path.parent / ".env"
    else:
        env_path = Path(env_path)

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    _scan_forbidden(data)

    runtime_raw = data.get("runtime")
    if not isinstance(runtime_raw, dict):
        raise ConfigError("missing [runtime] section")

    runtime = RuntimeConfig.model_validate(runtime_raw)
    credentials = Credentials()

    if env_path.is_file():
        env = _parse_env(env_path)
        _reject_env_flags(env)
        credentials = Credentials(
            mt5_login=env.get("MT5_LOGIN", ""),
            mt5_password=env.get("MT5_PASSWORD", ""),
            mt5_server=env.get("MT5_SERVER", ""),
            api_token=env.get("API_TOKEN", ""),
        )

    extras = {k: v for k, v in data.items() if k != "runtime"}
    return AppConfig(runtime=runtime, credentials=credentials, **extras)
