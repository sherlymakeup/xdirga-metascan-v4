// Runtime domain types for the XDirga Runtime V4 protocol.
// These types belong to the *frontend contract* the local backend must satisfy.
// The development fixture adapter is the reference implementation for UI development.

import type { CockpitSnapshot } from "@/lib/types";

// -----------------------------------------------------------------------------
// Frontend data source & execution semantics
// -----------------------------------------------------------------------------

/**
 * Where the frontend is currently reading data from.
 * - "DEVELOPMENT_FIXTURE": in-memory development fixtures (no runtime, no broker).
 * - "LOCAL_RUNTIME":       the local XDirga Runtime V4 backend via HTTP/SSE.
 *
 * This is a *data-source* dimension, not a trading mode. It never carries the
 * value "LIVE" (that is a broker/execution concept).
 */
export type FrontendDataSource = "DEVELOPMENT_FIXTURE" | "LOCAL_RUNTIME";

/** Target broker account environment. Metadata about the target — not proof of connectivity. */
export type BrokerEnvironment = "TRIAL" | "LIVE";

/** Execution safety semantics. Always LIVE-grade in this product. */
export type ExecutionSemantics = "LIVE";

/** @deprecated Use FrontendDataSource. Kept only for compatibility during migration. */
export type RuntimeMode = FrontendDataSource;

// -----------------------------------------------------------------------------
// Adapter descriptor (replaces `instanceof MockRuntimeAdapter` checks in UI)
// -----------------------------------------------------------------------------

export type RuntimeAdapterType = "DEVELOPMENT_FIXTURE" | "HTTP_LOCAL_RUNTIME";

export interface RuntimeAdapterDescriptor {
  adapterType: RuntimeAdapterType;
  dataSource: FrontendDataSource;
  /** True if this adapter must not be used to reason about real broker/runtime state. */
  isDevelopmentOnly: boolean;
}

// -----------------------------------------------------------------------------
// Connection lifecycle
// -----------------------------------------------------------------------------

export type RuntimeConnectionState =
  | "DISCONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "RECONNECTING"
  | "STALE"
  | "ERROR";

export interface RuntimeConnectionStateSnapshot {
  state: RuntimeConnectionState;
  /** Frontend data source this connection describes. */
  mode: FrontendDataSource;
  /** Low-level adapter tag. UI should prefer `RuntimeAdapterDescriptor`. */
  adapterType: "fixture" | "http";
  lastConnectedAt?: string;
  lastDisconnectedAt?: string;
  lastMessageAt?: string;
  lastHeartbeatAt?: string;
  roundTripLatencyMs?: number;
  reconnectAttempt: number;
  dataAgeMs?: number;
  errorCode?: string;
  errorMessage?: string;
}

/** Observed broker/gateway connection state — distinct from `BrokerTargetMetadata`. */
export interface BrokerConnectionSnapshot {
  state: "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "ERROR";
  serverName?: string;
  accountIdMasked?: string;
  tradingPermission?: boolean;
  lastHeartbeatAt?: string;
  lastSuccessfulRequestAt?: string;
  latencyMs?: number;
}

/** Target broker metadata — declarative, does not imply connectivity. */
export interface BrokerTargetMetadata {
  provider: "EXNESS";
  environment: BrokerEnvironment;
  executionSemantics: ExecutionSemantics;
}

// -----------------------------------------------------------------------------
// Snapshot metadata & event envelope
// -----------------------------------------------------------------------------

export interface SnapshotMetadata {
  runtimeId: string;
  bootId: string;
  revision: number;
  sequence: number;
  generatedAt: string;
  serverTimestamp: string;

  /** Protocol identifier, e.g. "xdirga-runtime-v4". */
  protocolId: string;
  /** Protocol version, e.g. "4.0.0". Distinct from protocolId. */
  protocolVersion: string;

  schemaVersion: string;
  schemaHash: string;

  /** Which frontend data source produced this snapshot. */
  source: FrontendDataSource;
}

/**
 * @deprecated Use `EventSeverity` from `./events/runtime-event-envelope`.
 * Retained only for compatibility with pre-Phase-5F imports.
 */
export type RuntimeEventSeverity = "TRACE" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

// The authoritative envelope + event type catalog lives in
// ./events/runtime-event-envelope. Re-exported here so legacy imports
// (`from "@/lib/runtime/runtime-types"`) keep resolving to the same type.
export type {
  RuntimeEventEnvelope,
  RuntimeEventType,
  EventSeverity,
} from "./events/runtime-event-envelope";
export { RUNTIME_EVENT_TYPES } from "./events/runtime-event-envelope";

export interface RuntimeSnapshotEnvelope {
  metadata: SnapshotMetadata;
  snapshot: CockpitSnapshot;
}

// -----------------------------------------------------------------------------
// Capabilities
// -----------------------------------------------------------------------------

export type RuntimeCommandKind =
  | "runtime.start"
  | "runtime.pause"
  | "runtime.resume"
  | "runtime.stop"
  | "runtime.restart"
  | "runtime.reconnectBroker"
  | "runtime.reconcile"
  | "runtime.disableEntries"
  | "runtime.enableEntries"
  | "runtime.emergencyKill"
  | "strategy.pause"
  | "strategy.resume"
  | "strategy.disable"
  | "order.cancel"
  | "order.cancelAll"
  | "position.close"
  | "position.closePartial"
  | "position.modifyProtection"
  | "position.closeAll"
  | "position.management.pause"
  | "position.management.resume"
  | "breaker.reset"
  | "alert.acknowledge"
  | "incident.acknowledge"
  | "config.validate"
  | "config.apply"
  | "config.rollback";

export interface CommandCapability {
  command: RuntimeCommandKind;
  allowed: boolean;
  reason?: string;
  riskLevel: 1 | 2 | 3 | 4;
  requiresReason: boolean;
  requiresTypedConfirmation: boolean;
  confirmationPhrase?: string;
}

export interface RuntimeCapabilities {
  revision: number;
  generatedAt: string;
  /** Which frontend data source produced this capability set. */
  source: FrontendDataSource;
  commands: Partial<Record<RuntimeCommandKind, CommandCapability>>;
}

// -----------------------------------------------------------------------------
// Command lifecycle
// -----------------------------------------------------------------------------

export interface RuntimeCommandRequest {
  clientRequestId: string;
  idempotencyKey: string;
  correlationId: string;
  kind: RuntimeCommandKind;
  targetId?: string;
  expectedRevision?: number;
  reason?: string;
  parameters?: Record<string, unknown>;
  submittedAt: string;
}

export type RuntimeCommandState =
  | "PREPARED"
  | "SUBMITTING"
  | "ACCEPTED"
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "FAILED"
  | "TIMED_OUT"
  | "EXECUTION_UNKNOWN"
  | "CANCELLED";

export interface CommandAccepted {
  commandId: string;
  clientRequestId: string;
  correlationId: string;
  state: "ACCEPTED";
  acceptedAt: string;
}

export interface RuntimeCommandStatus {
  commandId: string;
  clientRequestId: string;
  correlationId: string;
  idempotencyKey: string;
  kind: RuntimeCommandKind;
  targetId?: string;
  state: RuntimeCommandState;
  progress?: number;
  currentStep?: string;
  message?: string;
  errorCode?: string;
  errorMessage?: string;
  reason?: string;
  createdAt: string;
  updatedAt: string;
  completedAt?: string;
}

// -----------------------------------------------------------------------------
// Operator identity (mocked in fixture mode)
// -----------------------------------------------------------------------------

export type OperatorRole = "VIEWER" | "OPERATOR" | "RISK_MANAGER" | "ADMIN";

export interface OperatorIdentity {
  operatorId: string;
  displayName: string;
  role: OperatorRole;
  sessionId: string;
  authenticatedAt: string;
  simulated: boolean;
}

// -----------------------------------------------------------------------------
// Handshake & schema compatibility
// -----------------------------------------------------------------------------

/**
 * Handshake payload declared by the runtime at the start of every session
 * (or refreshed on reconnect). The frontend decides compatibility from this —
 * the backend cannot self-certify.
 */
export interface RuntimeHandshake {
  runtimeName: string;
  runtimeVersion: string;
  runtimeId: string;
  bootId: string;

  protocolId: string;
  protocolVersion: string;

  schemaVersion: string;
  schemaHash: string;

  capabilitiesRevision: number;

  /** Optional lower bound the runtime places on the frontend build. */
  minFrontendVersion?: string;
  /** Frontend version echoed back by the runtime, when known. */
  frontendVersion?: string;

  supportedFeatures: string[];
  supportedCommands: RuntimeCommandKind[];

  brokerProvider?: "EXNESS";
  brokerEnvironment?: BrokerEnvironment;
  executionSemantics?: ExecutionSemantics;

  /** Which frontend data source generated this handshake (fixture vs. local runtime). */
  source: FrontendDataSource;

  observedAt: string;
}

export type HandshakeSeverity = "OK" | "WARN" | "INCOMPATIBLE";

export interface HandshakeReason {
  code: string;
  severity: HandshakeSeverity;
  message: string;
}

export interface HandshakeCompatibility {
  severity: HandshakeSeverity;
  /** True when the UI must gate commands (INCOMPATIBLE, missing handshake). */
  safeMode: boolean;
  reasons: HandshakeReason[];
  expected: {
    runtimeName: string;
    protocolId: string;
    protocolVersion: string;
    schemaVersion: string;
    schemaHash: string;
    minRuntimeVersion: string;
    requiredCommands: readonly RuntimeCommandKind[];
    safetyCriticalCommands: readonly RuntimeCommandKind[];
    requiredFeatures: readonly string[];
  };
  actual: RuntimeHandshake | null;
  evaluatedAt: string;
}

// -----------------------------------------------------------------------------
// Errors
// -----------------------------------------------------------------------------

export class NotImplementedError extends Error {
  constructor(what: string) {
    super(`${what} is not implemented. Awaiting XDirga Runtime V4 backend.`);
    this.name = "NotImplementedError";
  }
}
