"""CLI: python -m metascan.contract hash"""

from __future__ import annotations

import sys

from metascan.contract.hash import (
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    compute_schema_hash,
)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "hash":
        print("usage: python -m metascan.contract hash", file=sys.stderr)
        raise SystemExit(2)
    # Print only the hash for stable scripting; versions available via API.
    print(compute_schema_hash())
    # silence unused in CLI path for package metadata consumers
    _ = (PROTOCOL_VERSION, SCHEMA_VERSION)


if __name__ == "__main__":
    main()
