PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
  boot_id       TEXT    NOT NULL,
  sequence      INTEGER NOT NULL,
  type          TEXT    NOT NULL,
  entity_id     TEXT    NULL,
  ts            TEXT    NOT NULL,
  envelope_json TEXT    NOT NULL,
  PRIMARY KEY (boot_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_events_boot_seq   ON events (boot_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_boot_type  ON events (boot_id, type);
CREATE INDEX IF NOT EXISTS idx_events_entity     ON events (boot_id, entity_id)
  WHERE entity_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events is append-only: DELETE forbidden');
END;

CREATE TABLE IF NOT EXISTS commands (
  command_id         TEXT PRIMARY KEY,
  idempotency_key    TEXT NOT NULL UNIQUE,
  client_request_id  TEXT NOT NULL,
  correlation_id     TEXT NOT NULL,
  kind               TEXT NOT NULL,
  target_id          TEXT NULL,
  state              TEXT NOT NULL,
  progress           REAL NULL,
  current_step       TEXT NULL,
  message            TEXT NULL,
  error_code         TEXT NULL,
  created_at         TEXT NOT NULL,
  updated_at         TEXT    NOT NULL,
  request_json       TEXT    NOT NULL DEFAULT '{}',
  origin             TEXT    NOT NULL CHECK(origin IN ('TRANSPORT','INTERNAL')),
  execution_kind     TEXT    NULL,
  record_json        TEXT    NULL,
  internal_record_json TEXT  NULL,
  CHECK (
    (origin = 'TRANSPORT' AND execution_kind IS NULL AND record_json IS NOT NULL AND internal_record_json IS NULL)
    OR
    (origin = 'INTERNAL' AND execution_kind IS NOT NULL AND record_json IS NULL AND internal_record_json IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS entry_intents (
  symbol          TEXT PRIMARY KEY,
  command_id      TEXT NOT NULL,
  state           TEXT NOT NULL,
  order_ticket    INTEGER NULL,
  deal_ticket     INTEGER NULL,
  position_ticket INTEGER NULL
);

CREATE TABLE IF NOT EXISTS command_transitions (
  boot_id         TEXT    NOT NULL,
  sequence        INTEGER NOT NULL,
  command_id      TEXT    NOT NULL,
  from_state      TEXT    NULL,
  to_state        TEXT    NOT NULL,
  ts              TEXT    NOT NULL,
  transition_json TEXT    NOT NULL,
  PRIMARY KEY (boot_id, sequence, command_id)
);

CREATE INDEX IF NOT EXISTS idx_cmd_transitions_cmd
  ON command_transitions (command_id, boot_id, sequence);

CREATE TRIGGER IF NOT EXISTS command_transitions_no_update
BEFORE UPDATE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS command_transitions_no_delete
BEFORE DELETE ON command_transitions
BEGIN
  SELECT RAISE(ABORT, 'command_transitions is append-only: DELETE forbidden');
END;

CREATE TABLE IF NOT EXISTS runtime_state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
