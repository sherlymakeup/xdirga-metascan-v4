# SP4 Implementation Plan: FastAPI & Web Server (Transport)

## 1. Overview
This plan implements the authoritative HTTP/SSE transport layer (SP4) for the XDirga Metascan V4 application using FastAPI. It bridges the frontend V4 contract to the backend `EventBus` and `Journal` implemented in SP2, enforcing strict payload matching and secure, gapless SSE state delivery.

## 2. Directory Structure

All new files will be placed under the existing `backend` directory.

```
backend/
├── src/
│   └── metascan/
│       ├── web/                    # New directory for SP4
│       │   ├── __init__.py
│       │   ├── app.py              # FastAPI instance, exception handlers, lifecycle
│       │   ├── dependencies.py     # DI for EventBus, Journal, Config, etc.
│       │   ├── security.py         # Token auth logic (Bearer / query param)
│       │   ├── sse.py              # SSE stream management (Race-Free Splice)
│       │   └── routers/            # Endpoint groups
│       │       ├── __init__.py
│       │       ├── handshake.py    # /v4/handshake
│       │       ├── health.py       # /v4/health, /v4/ops/metrics
│       │       ├── command.py      # /v4/command
│       │       ├── journal.py      # /v4/journal/*
│       │       └── stream.py       # /v4/stream, /v4/snapshot
├── tests/
│   └── test_web/                   # New test directory
│       ├── __init__.py
│       ├── conftest.py             # FastAPI test client and mock DI fixtures
│       ├── test_api_handshake.py
│       ├── test_api_health.py
│       ├── test_api_commands.py
│       ├── test_api_journal.py
│       ├── test_api_sse.py         # SSE handoff, redaction, queue overflow control frames
│       └── test_api_lifecycle.py
```

## 3. Strict TDD Implementation Steps

### Step 3.1: Scaffolding, Models, & Security (Prerequisites)
1. **Models/Contracts:** Create `src/metascan/web/models.py` (or define in routers) matching EXACTLY `src/lib/runtime/runtime-contract.ts` and `runtime-types.ts` shapes (`EXPECTED_RUNTIME_CONTRACT`, `FrontendDataSource`, etc.).
2. **Security:** Implement `src/metascan/web/security.py`. Extract token from `Authorization: Bearer <token>` or `?token=<token>`. Verify against `AppConfig.credentials.api_token` (from SP1).
3. **App & DI:**
   - Create `dependencies.py`: Provide `EventBus`, `Journal`, `AppConfig`. (Mocked for tests via `app.dependency_overrides`).
   - Create `app.py`: Initialize `FastAPI`, add custom exception handlers (e.g., mask 401s if needed, standard JSON error formatting).
4. **Test:** Write `test_web/conftest.py` setting up `TestClient`.

### Step 3.2: Handshake & Health (Stateless)
1. **Tests:**
   - `test_api_handshake.py`: Check GET `/v4/handshake` matches `EXPECTED_RUNTIME_CONTRACT` (protocolId, schemaHash, etc.).
   - `test_api_health.py`:
     - GET `/v4/health` returns `status` (OK/DEGRADED), `mt5_connected`, `db_ok`, `uptime`.
     - GET `/v4/ops/metrics` returns `eventBusQueueSize`, `mt5PollLatencyMs`, `sqliteCommitLatencyMs`, `activeSseConnections`.
2. **Implementation:**
   - `routers/handshake.py`
   - `routers/health.py`
   - Wire into `app.py`.

### Step 3.3: Commands & Journal (Write/Read)
1. **Tests:**
   - `test_api_commands.py`: POST `/v4/command` accepts valid `RuntimeCommandKind`, returns `{status, commandId, correlationId}`. Validate insertion into Journal (via mock Journal dependency). Enforce no execution (idempotent, mock execution for SP4).
   - `test_api_journal.py`:
     - GET `/v4/journal/session`: Returns current session.
     - GET `/v4/journal/calendars`: Returns list, blocks OPEN sessions.
     - GET `/v4/journal/trades`: Returns `trade.closed` events.
2. **Implementation:**
   - `routers/command.py`: Parse `RuntimeCommandRequest`, validate `kind`.
   - `routers/journal.py`: Query `Journal` endpoints. Ensure strict mapping to frontend shapes.

### Step 3.4: The Race-Free Splice (SSE & Snapshot)
1. **Tests:** `test_api_sse.py`
   - Test GET `/v4/snapshot`: Returns state lock with `sequence`.
   - Test GET `/v4/stream` (mocking `EventBus` yielding).
   - **Crucial:** Test the handoff logic: subscriber subscribes, captures max sequence, queries Journal > max sequence, drops queued events <= max sequence, streams remainder.
   - Test auth token redaction in logs (check structlog output or mock).
   - Test `system.resync.required` frame triggered by `EventBus` overflow or `bootId` mismatch.
   - Test 15s ping heartbeat generation.
2. **Implementation:**
   - `src/metascan/web/sse.py`: Use `asyncio` Generators. Implement `Server-Sent Events` format (`data: ...\n\n`).
   - `routers/stream.py`: Handle `/v4/snapshot` and `/v4/stream`. Enforce `bootId` check.

### Step 3.5: App Lifecycle
1. **Tests:** `test_api_lifecycle.py`
   - Test `lifespan` context manager in `app.py` initializes DB, creates EventBus, starts background threads (if mocked), and cleanly shuts them down on exit.
2. **Implementation:** Complete `app.py` lifespan events.

## 4. Final Review & Commit
- Verify all `/v4/*` routes exist.
- Verify `bootId` is strictly checked.
- Verify protocol shapes match V4 contract exactly.
- Verify `pytest backend/tests/test_web/ -v` passes 100%.

**Final Commit Message:** `SP4: FastAPI transport + SSE`