# Live read-only entrypoint; seam mutasi tetap terkunci di web layer.
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from metascan.config import ConfigError, load_config
from metascan.web.composition import create_wired_app


def build_live_app(
    *, config_path: Path | str | None = None, mt5_module: Any = None
) -> FastAPI:
    try:
        cfg = load_config(config_path=config_path)
    except (ConfigError, OSError, ValueError) as exc:
        raise SystemExit(f"config load gagal: {exc}") from exc

    env_path = Path(config_path or "config.toml").parent / ".env"
    if not cfg.credentials.api_token.strip():
        raise SystemExit(f"API_TOKEN kosong di {env_path} — dashboard auth wajib")

    credentials = {
        "MT5_LOGIN": cfg.credentials.mt5_login,
        "MT5_PASSWORD": cfg.credentials.mt5_password,
        "MT5_SERVER": cfg.credentials.mt5_server,
    }
    for name, value in credentials.items():
        if not os.environ.get(name, "").strip() and value.strip():
            os.environ[name] = value

    missing = [name for name in credentials if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit(
            f"env MT5 wajib belum lengkap di {env_path}: {', '.join(missing)}; "
            f"gunakan backend/.env.example sebagai format lalu isi {env_path}"
        )

    if mt5_module is None:
        try:
            mt5_module = importlib.import_module("MetaTrader5")
        except ImportError as exc:
            raise SystemExit(
                "MetaTrader5 tidak tersedia; install manual package MetaTrader5 di PC Windows"
            ) from exc

    watchlist = (
        tuple(cfg.runtime.symbols.watchlist)
        if cfg.runtime.symbols and cfg.runtime.symbols.watchlist
        else ("XAUUSD",)
    )
    return create_wired_app(
        config=cfg,
        bot_magic=cfg.runtime.bot_magic,
        mt5_module=mt5_module,
        watchlist_bases=watchlist,
        symbol_suffix=cfg.runtime.symbol_suffix,
    )


def main() -> None:
    app = build_live_app()
    uvicorn.run(app, host="127.0.0.1", port=8787)


if __name__ == "__main__":
    main()
