from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_commands_transport_requires_auth(async_client) -> None:
    # HANDOFF.md §10: REST command transport requires Bearer auth.
    response = await async_client.post(
        "/v4/commands",
        json={"kind": "runtime.pause", "idempotencyKey": "sp5-no-auth"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_command_is_indistinguishable_from_absent_command(async_client, journal_db) -> None:
    journal_db.run_on_writer(
        lambda conn: (
            conn.execute(
                """INSERT INTO commands (
                  command_id, idempotency_key, client_request_id, correlation_id, kind, target_id,
                  state, created_at, updated_at, request_json, origin, execution_kind,
                  record_json, internal_record_json
                ) VALUES ('internal', 'internal-key', 'internal-client', 'internal-correlation',
                  'entry.market', NULL, 'PREPARED', 't', 't', '{}', 'INTERNAL',
                  'INTERNAL_ENTRY_MARKET', NULL, '{}')"""
            ),
            conn.commit(),
        )
    )
    headers = {"Authorization": "Bearer test-token-123"}
    internal = await async_client.get("/v4/commands/internal", headers=headers)
    missing = await async_client.get("/v4/commands/missing", headers=headers)
    assert internal.status_code == missing.status_code == 404
    assert internal.json() == missing.json()


@pytest.mark.asyncio
async def test_unknown_transport_kind_rejects_before_journal_write(async_client, journal_db) -> None:
    response = await async_client.post(
        "/v4/commands",
        json={"kind": "internal.entry", "idempotencyKey": "unknown-kind"},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert response.status_code == 422
    assert journal_db.run_on_writer(lambda conn: conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0]) == 0
