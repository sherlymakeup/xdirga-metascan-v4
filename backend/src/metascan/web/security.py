from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, APIKeyQuery

from metascan.config import AppConfig
from metascan.web.dependencies import get_config

_header_scheme = APIKeyHeader(name="Authorization", auto_error=False)
_query_scheme = APIKeyQuery(name="token", auto_error=False)

# Sentinel returned by verify_token — callers receive proof of auth
# without holding the raw token value in handler signatures.
_AUTH_OK = "AUTHENTICATED"


def verify_token(
    header_token: str | None = Security(_header_scheme),
    query_token: str | None = Security(_query_scheme),
    config: AppConfig = Depends(get_config),
) -> str:
    token: str | None = None
    if header_token and header_token.startswith("Bearer "):
        token = header_token[len("Bearer "):]
    elif query_token:
        token = query_token

    expected = config.credentials.api_token
    # hmac.compare_digest prevents timing-oracle attacks on token comparison.
    # Both operands must be non-empty strings of equal type.
    valid = bool(
        token
        and expected
        and hmac.compare_digest(token.encode(), expected.encode())
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Return opaque sentinel — not the raw token — so handler signatures
    # never carry secret material.
    return _AUTH_OK
