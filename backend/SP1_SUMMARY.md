# SP1 — Contract skeleton + schema hash

## Scope delivered

- `backend/` uv Python 3.12 project (`pyproject.toml`, package `metascan`)
- `config.toml` + credential-only `.env` loading (`metascan.config`)
- Reject demo/mock/paper runtime flags (env + toml keys/values)
- Secrets never in `repr` / `str` / `model_dump` (`Credentials` redaction)
- Hand-written Pydantic v2 models for event + command + snapshot surface
- snake_case internal / camelCase wire aliases (`alias_generator`)
- Enum spellings exact to TS (management actions, TradeExitReason, catalogs)
- Drift guard pytest parses authoritative TS registries (exact set equality)
- Canonical sorted compact JSON SHA-256 over full schema document
- CLI: `python -m metascan.contract hash`
- Root `.gitignore`: `backend/.env`, `backend/.venv`, `__pycache__/`, `*.sqlite`

## Decisions

### TradeExitReason / MANUAL override

- TS authority (`src/lib/types.ts`): `TP | SL | TRAIL | PARTIAL_FINAL | MANUAL | TIME_EXIT | KILL_SWITCH | BREAKER | OTHER`
- **No `MANUAL_CLOSE` anywhere** in the domain model
- External / manual / operator broker closes map via `map_exit_reason(...)` → **`MANUAL`**
- Phase-1 prompt text mentioning `MANUAL_CLOSE` is overridden by this decision and the TS contract

### Event registry location

- Authoritative list is `RUNTIME_EVENT_TYPES` in `runtime-event-envelope.ts` (not the payload file `event-schemas.ts`)
- Drift guard reads that file; command kinds from `RuntimeCommandKind` union in `runtime-types.ts`

### Versions

- `protocolVersion` = `4.1.0`
- `schemaVersion` = `1.1.0` (from `runtime-contract.ts`)
- Golden hash pinned in `metascan.contract.hash.GOLDEN_SCHEMA_HASH`

### Forbidden runtime modes (config)

- Reject keys containing `demo|mock|paper|fixture|simulation`
- Reject **whole scalar values** equal (casefold) to those tokens on any key
  (e.g. `execution_semantics = "demo"`)
- No false-positives on paths/names (`data/demo-notes-archive`, `paperplane`)

### Wire serialization

- `WireModel`: `serialize_by_alias=True` — camelCase on dump / TypeAdapter / FastAPI
- **No blanket `exclude_none` override** on `model_dump`
- `@model_serializer(mode="wrap")`: keep **required-nullable** as explicit `null`; omit only fields that are **not required** and currently `None` (TS optional)
- Examples: `ClosedTrade.rMultiple|mfeR|maeR` and `TradeHistoryPage.nextCursor` → `null` when null; envelope `correlationId` omitted when unset

### Event envelope / catalogs

- `RuntimeEventEnvelope.payload` required (no default), matching TS
- `type` and command `kind` are closed str Enums over exact TS catalogs (unknown rejected; JSON Schema enums)

### Config nested / env defaults

- `RuntimeConfig.symbols.watchlist` supports shipped `[runtime.symbols]`
- Default `.env` path = adjacent to `config.toml` when `env_path` omitted
- No `pydantic-settings` dependency

### Schema hash stability

- Pin `pydantic==2.13.4` in `pyproject.toml` / lock
- Strip non-semantic `title`/`description` keys before canonical SHA-256

### MANUAL_CLOSE

- **No `MANUAL_CLOSE` literal** in Python contract surface or tests
- `map_exit_reason` accepts only external/manual/operator/user → `MANUAL`

## Not in SP1

- FastAPI / SSE / MT5 gateway / journal (later phases)
- No credentials or generated secrets committed
