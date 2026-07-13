from __future__ import annotations

# GET /v4/history/trades?cursor=&limit= — §10.6
# Paginated closed-trade history backed by journal trade.closed events.
# cursor is opaque: base-10 string encoding the last-seen sequence (exclusive).
# limit default 100, max 500.
# Dedup key: tradeId — live trade.closed event wins over backfill (enforced by
# frontend cache; backend returns rows ordered newest-first).
# Contract source: HANDOFF.md §10.6, runtime-types.ts TradeHistoryPage.

import sqlite3

from fastapi import APIRouter, Depends, Query

from metascan.journal.db import Journal
from metascan.web.dependencies import get_journal
from metascan.web.security import verify_token

router = APIRouter()

_MAX_LIMIT = 500
_DEFAULT_LIMIT = 100


def _parse_cursor(cursor: str | None) -> int | None:
    """Decode opaque cursor → sequence value (exclusive upper bound for DESC)."""
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError:
        return None


def _encode_cursor(sequence: int) -> str:
    return str(sequence)


def _fetch_trades(
    journal: Journal,
    after_cursor: int | None,
    limit: int,
) -> tuple[list[dict], str | None]:
    """Query journal for trade.closed envelope payloads, newest-first.

    Returns (trades_list, next_cursor_or_None).
    Cursor encodes the sequence of the last row returned; pass back to get older rows.
    """
    def _query(conn: sqlite3.Connection):
        if after_cursor is None:
            rows = conn.execute(
                """
                SELECT sequence, envelope_json FROM events
                WHERE type = 'trade.closed'
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (limit + 1,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT sequence, envelope_json FROM events
                WHERE type = 'trade.closed' AND sequence < ?
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (after_cursor, limit + 1),
            ).fetchall()
        return rows

    rows = journal.run_on_writer(_query)

    has_more = len(rows) > limit
    page = rows[:limit]

    trades: list[dict] = []
    for row in page:
        try:
            import json
            envelope = json.loads(row["envelope_json"] if hasattr(row, "__getitem__") else row[1])
            payload = envelope.get("payload", {})
            trades.append(payload)
        except Exception:
            continue

    next_cursor: str | None = None
    if has_more and page:
        last_seq = page[-1]["sequence"] if hasattr(page[-1], "__getitem__") else page[-1][0]
        next_cursor = _encode_cursor(last_seq)

    return trades, next_cursor


@router.get("/history/trades")
async def get_trade_history(
    cursor: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    journal: Journal = Depends(get_journal),
    _token: str = Depends(verify_token),
) -> dict:
    after_cursor = _parse_cursor(cursor)
    trades, next_cursor = _fetch_trades(journal, after_cursor, limit)
    return {
        "trades": trades,
        "nextCursor": next_cursor,
    }
