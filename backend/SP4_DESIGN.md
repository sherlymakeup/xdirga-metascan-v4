# SP4: FastAPI & Web Server Implementation Design

## 1. Goal

Provide the authoritative web layer (HTTP/SSE) serving the V4 Frontend Contract. This encapsulates auth, exact endpoint shape, connection lifecycle, state locks (snapshots), and precise replay synchronization over SQLite + EventBus.

## 2. API Contract (Strict V4 Compliance)

The backend MUST match these exact shapes requested by the frontend.
All HTTP endpoints are prefixed with `/v4`.

### 2.1 Boot & Handshake

`GET /v4/handshake`
*   **Returns:** Exact `EXPECTED_RUNTIME_CONTRACT` layout matching `src/lib/runtime/runtime-contract.ts`.
*   **Purpose:** Allows frontend to verify protocol (`protocolVersion`, `schemaHash`, `schemaVersion`).

### 2.2 Health & Metrics

`GET /v4/health`
*   **Returns:** Computed pure SLO evaluator payload.
    *   `status`: "OK" | "DEGRADED" | "DOWN"
    *   `mt5_connected`: boolean
    *   `db_ok`: boolean
    *   `uptime`: seconds
    *   *No internal system metrics (e.g., GC pauses, thread count) here.*

`GET /v4/ops/metrics`
*   **Returns:** Backend-owned detailed ops metrics (camelCase).
    *   `eventBusQueueSize`: number
    *   `mt5PollLatencyMs`: number
    *   `sqliteCommitLatencyMs`: number
    *   `activeSseConnections`: number

### 2.3 Command Submission

`POST /v4/command`
*   **Request Body:** `CommandPayload` (matches `CommandKind` and exact payloads defined in `frontend/src/lib/runtime/runtime-types.ts`).
*   **Returns:** `{ "status": "accepted", "commandId": "...", "correlationId": "..." }`
*   **Deterministic Execution (SP4 constraint):**
    *   Commands are inserted into the Journal (created -> accepted/failed).
    *   *No MT5 mutation occurs in SP4.* Command execution is disabled.
    *   Idempotent replay logic ensures duplicate submissions are dropped or handled safely.

### 2.4 History & Trades (Journal)

`GET /v4/journal/session`
*   **Returns:** The *current* active trading session timeline (orders, commands).

`GET /v4/journal/calendars`
*   **Returns:** List of closed/past sessions.
*   **Constraint:** Excludes default unlisted OPEN sessions. Fails loud if queried improperly.

`GET /v4/journal/trades`
*   **Returns:** List of closed trades matching the `trade.closed` envelope shape (grossPnl, commission, swap, netPnl, exitReason).

### 2.5 State Lock (Snapshot)

`GET /v4/snapshot`
*   **Returns:** Current aggregated state of the runtime (Positions, Orders, Circuit Breakers, Global State) at a specific sequence number.
*   **Constraint:** Snapshot state lock captures the exact `sequence` for seamless SSE handoff.

---

## 3. SSE Transport (Events)

`GET /v4/stream`

### 3.1 Auth & Connection

*   **Auth:** Requires valid `Bearer` token in `Authorization` header OR `token` query param.
*   **Redaction:** Tokens MUST be redacted in logs. No token material in the Journal.
*   **Query Rules (`bootId`):**
    *   Must include `bootId`.
    *   Can be `BOOT_ID_UNKNOWN` if the frontend doesn't know it yet.
    *   If numeric overlap/mismatch detected against current backend bootId, connection is rejected.

### 3.2 Race-Free Splice (The Handoff)

To ensure no dropped or duplicate events between `/v4/snapshot` and `/v4/stream`:

1.  **Under EventBus Publish Lock:**
    *   Subscribe to EventBus.
    *   Capture boundary (current max sequence).
2.  **Release Lock.**
3.  **Replay:** Query Journal for events strictly `> boundary` (if `lastEventId` provided) or `> snapshot_sequence`.
4.  **Queue Discard:** Discard any events from the live EventBus queue where `sequence <= boundary`.
5.  **Streaming:** Begin pushing live events from the queue.

*   **Precondition:** SP2 append (SQLite commit) MUST complete *before* EventBus publish. Assert/comment/test this explicitly.
*   **Result:** No gap, no duplication during concurrent replay.

### 3.3 Protocol Frames & Heartbeats

*   **Heartbeats:** Empty comment `:\n\n` or explicit `{"type": "ping"}` sent every 15s to keep connection alive.
*   **Control Frame (`system.resync.required`):**
    *   Sent when the client falls too far behind or misses events.
    *   **Shape:** Non-envelope, non-journal, no ID union.
    *   **Reasons (4 exact unions):** `["GAP_DETECTED", "QUEUE_OVERFLOW", "BOOT_MISMATCH", "INTERNAL_ERROR"]`.
    *   **Action:** Connection STAYS OPEN. The frontend is responsible for requesting a new snapshot and reconnecting if necessary.

---

## 4. Architecture & Lifecycle

### 4.1 Layers
*   `app.py`: FastAPI application setup, middleware, exception handlers.
*   `api.py` / `routers/`: Endpoint definitions (`/v4/...`).
*   `sse.py`: The SSE streaming logic, connection manager, and Race-Free Splice implementation.
*   `dependencies.py`: FastAPI DI for EventBus, Journal, MT5 Gateway (mocked for SP4).

### 4.2 Error Handling
*   Strict Pydantic validation (422 Unprocessable Entity).
*   Domain exceptions map to standard HTTP codes (400 Bad Request, 404 Not Found, 409 Conflict).
*   All errors returned as JSON: `{"error": "...", "code": "...", "details": {...}}`.

### 4.3 Lifecycle
*   **Startup:** Initialize DB (SP2), EventBus (SP2), MT5 Gateway background thread (mocked).
*   **Shutdown:** Signal threads to stop, flush journal, close DB.

---

## 5. ASGI Tests

*   `test_api_handshake.py`: Verifies `/v4/handshake` matches UI contract.
*   `test_api_sse.py`: Verifies SSE connection, auth redaction, race-free splice, and control frames.
*   `test_api_commands.py`: Verifies `/v4/command` deterministic flow (no MT5 mutation).
*   `test_api_journal.py`: Verifies `/v4/journal/*` endpoints and calendar exclusions.
*   `test_api_health.py`: Verifies pure SLO payload and separate metrics payload.
*   `test_api_lifecycle.py`: Startup/shutdown hooks.

---

## 6. Contract Notes & Rules

*   **No Placeholders:** All endpoints must have full logic, no `pass` or `TODO` (except MT5 execution which is explicitly disabled in SP4).
*   **Check Actual Frontend Shapes:** Always reference `frontend/src/types/*` and `src/lib/runtime/*`. If unresolved conflict, STOP and state blocker.
*   **Self-Review:** Ensure exact matching of enum values (e.g., `EventSeverity`, `FrontendDataSource`, `EventSourceState`).
