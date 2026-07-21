// Fixture adapter — the reference implementation of RuntimeAdapter that powers
// the frontend from local development fixtures. This is NOT a trading mode. It
// is a *frontend data source* used while there is no local XDirga Runtime V4
// backend and no broker (MT5 / Exness TRIAL) connection.
//
// Safety semantics are LIVE-grade: commands go through the full command
// lifecycle, but nothing is ever executed on a real broker.

import { buildSnapshot, getFixtureTradeHistory, SCENARIOS } from "@/lib/demo/scenarios";
import type {
  CockpitSnapshot,
  ScenarioKey,
  TradeHistoryPage,
  TradeHistoryQuery,
} from "@/lib/types";
import type { RuntimeAdapter } from "./runtime-adapter";
import { buildCapabilities } from "./runtime-capabilities";
import { EXPECTED_RUNTIME_CONTRACT, RUNTIME_CONTRACT } from "./runtime-contract";
import { commandStore } from "./runtime-command-store";
import type {
  CommandAccepted,
  OperatorIdentity,
  RuntimeAdapterDescriptor,
  RuntimeCapabilities,
  RuntimeCommandRequest,
  RuntimeCommandStatus,
  RuntimeConnectionStateSnapshot,
  RuntimeEventEnvelope,
  RuntimeHandshake,
  RuntimeSnapshotEnvelope,
  SnapshotMetadata,
} from "./runtime-types";

const RUNTIME_ID = "rt_local_01HXDRG4";
let bootCounter = 1;
const BOOT_ID = () => `boot_${bootCounter}`;

function safeUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export interface MockAdapterOptions {
  /** Reserved for future fixture variants. Currently unused. */
  variant?: "development";
}

export class MockRuntimeAdapter implements RuntimeAdapter {
  readonly adapterType = "fixture" as const;

  private scenario: ScenarioKey = "healthy";
  private snapshot: CockpitSnapshot = buildSnapshot("healthy");
  private revision = 1;
  private sequence = 1;
  private snapshotListeners = new Set<(env: RuntimeSnapshotEnvelope) => void>();
  private eventListeners = new Set<(env: RuntimeEventEnvelope) => void>();
  private commandListeners = new Map<string, Set<(s: RuntimeCommandStatus) => void>>();
  private connectionListeners = new Set<(s: RuntimeConnectionStateSnapshot) => void>();
  private connection: RuntimeConnectionStateSnapshot;
  private capabilities: RuntimeCapabilities = buildCapabilities(this.snapshot);
  private operator: OperatorIdentity;
  private handshake: RuntimeHandshake;
  private handshakeMismatch: "none" | "minor" | "major" = "none";
  private handshakeListeners = new Set<(h: RuntimeHandshake | null) => void>();

  constructor(_opts: MockAdapterOptions = {}) {
    void _opts;
    this.connection = {
      state: "CONNECTED",
      mode: "DEVELOPMENT_FIXTURE",
      adapterType: "fixture",
      lastConnectedAt: new Date().toISOString(),
      lastMessageAt: new Date().toISOString(),
      lastHeartbeatAt: new Date().toISOString(),
      roundTripLatencyMs: 0,
      reconnectAttempt: 0,
      dataAgeMs: 0,
    };
    this.operator = {
      operatorId: "op_dev_fixture",
      displayName: "Development Fixture",
      role: "OPERATOR",
      sessionId: `sess_${safeUuid()}`,
      authenticatedAt: new Date().toISOString(),
      simulated: true,
    };
    this.handshake = this.buildHandshake();
  }

  private buildHandshake(): RuntimeHandshake {
    const mismatch = this.handshakeMismatch;
    const base: RuntimeHandshake = {
      runtimeName: EXPECTED_RUNTIME_CONTRACT.runtimeName,
      runtimeVersion: RUNTIME_CONTRACT.minRuntimeVersion,
      runtimeId: RUNTIME_ID,
      bootId: BOOT_ID(),
      protocolId: RUNTIME_CONTRACT.protocolId,
      protocolVersion: RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: RUNTIME_CONTRACT.schemaVersion,
      schemaHash: RUNTIME_CONTRACT.schemaHash,
      capabilitiesRevision: this.revision,
      minFrontendVersion: RUNTIME_CONTRACT.minFrontendVersion,
      frontendVersion: RUNTIME_CONTRACT.frontendVersion,
      supportedFeatures: [...EXPECTED_RUNTIME_CONTRACT.requiredFeatures],
      supportedCommands: [...EXPECTED_RUNTIME_CONTRACT.requiredCommands],
      brokerProvider: "EXNESS",
      brokerEnvironment: "TRIAL",
      executionSemantics: "LIVE",
      source: "DEVELOPMENT_FIXTURE",
      observedAt: new Date().toISOString(),
    };
    if (mismatch === "minor") {
      return {
        ...base,
        protocolVersion: "4.1.0",
        schemaHash: "dev-schema-drifted-minor",
        supportedCommands: base.supportedCommands.filter((c) => c !== "config.validate"),
      };
    }
    if (mismatch === "major") {
      return {
        ...base,
        protocolVersion: "5.0.0",
        schemaVersion: "2.0.0",
        supportedCommands: base.supportedCommands.filter((c) => c !== "runtime.emergencyKill"),
      };
    }
    return base;
  }

  /** Dev-only: rebuild handshake at a chosen mismatch level. */
  simulateHandshakeMismatch(kind: "none" | "minor" | "major"): void {
    if (this.handshakeMismatch === kind) return;
    this.handshakeMismatch = kind;
    this.handshake = this.buildHandshake();
    for (const l of this.handshakeListeners) l(this.handshake);
  }
  getHandshakeMismatch(): "none" | "minor" | "major" {
    return this.handshakeMismatch;
  }

  // ---- Handshake ----------------------------------------------------------
  getHandshake(): RuntimeHandshake | null {
    return this.handshake;
  }
  async refreshHandshake(): Promise<RuntimeHandshake> {
    this.handshake = this.buildHandshake();
    for (const l of this.handshakeListeners) l(this.handshake);
    return this.handshake;
  }
  subscribeHandshake(listener: (h: RuntimeHandshake | null) => void): () => void {
    this.handshakeListeners.add(listener);
    return () => {
      this.handshakeListeners.delete(listener);
    };
  }

  // ---- Lifecycle ----------------------------------------------------------
  async connect(): Promise<void> {
    /* fixture adapter is always "connected" to its in-memory data source */
  }
  async disconnect(): Promise<void> {
    /* no-op */
  }

  // ---- Snapshots ----------------------------------------------------------
  getSnapshot(): CockpitSnapshot {
    return this.snapshot;
  }

  private buildMetadata(): SnapshotMetadata {
    const now = new Date().toISOString();
    return {
      runtimeId: RUNTIME_ID,
      bootId: BOOT_ID(),
      revision: this.revision,
      sequence: this.sequence,
      generatedAt: now,
      serverTimestamp: now,
      protocolId: RUNTIME_CONTRACT.protocolId,
      protocolVersion: RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: RUNTIME_CONTRACT.schemaVersion,
      schemaHash: RUNTIME_CONTRACT.schemaHash,
      source: "DEVELOPMENT_FIXTURE",
    };
  }

  getSnapshotEnvelope(): RuntimeSnapshotEnvelope {
    return { metadata: this.buildMetadata(), snapshot: this.snapshot };
  }

  async refreshSnapshot(): Promise<RuntimeSnapshotEnvelope> {
    return this.getSnapshotEnvelope();
  }

  subscribeSnapshot(listener: (env: RuntimeSnapshotEnvelope) => void): () => void {
    this.snapshotListeners.add(listener);
    return () => {
      this.snapshotListeners.delete(listener);
    };
  }

  private emitSnapshot() {
    const env = this.getSnapshotEnvelope();
    for (const l of this.snapshotListeners) l(env);
  }

  // ---- Events -------------------------------------------------------------
  subscribeEvents(listener: (env: RuntimeEventEnvelope) => void): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  private emitEvent(
    type: RuntimeEventEnvelope["type"],
    payload: unknown,
    correlationId?: string,
    opts: {
      severity?: RuntimeEventEnvelope["severity"];
      commandId?: string;
      orderId?: string;
      positionId?: string;
      strategyId?: string;
      incidentId?: string;
      reconciliationRunId?: string;
    } = {},
  ) {
    this.sequence += 1;
    const now = new Date().toISOString();
    const env: RuntimeEventEnvelope = {
      eventId: `evt_${safeUuid()}`,
      type,
      runtimeId: RUNTIME_ID,
      bootId: BOOT_ID(),
      revision: this.revision,
      sequence: this.sequence,
      occurredAt: now,
      emittedAt: now,
      receivedAt: now,
      severity: opts.severity ?? "INFO",
      source: "DEVELOPMENT_FIXTURE",
      correlationId,
      commandId: opts.commandId,
      orderId: opts.orderId,
      positionId: opts.positionId,
      strategyId: opts.strategyId,
      incidentId: opts.incidentId,
      reconciliationRunId: opts.reconciliationRunId,
      payload,
    };
    for (const l of this.eventListeners) l(env);
  }

  // ---- Capabilities -------------------------------------------------------
  getCapabilities(): RuntimeCapabilities {
    return this.capabilities;
  }
  async refreshCapabilities(): Promise<RuntimeCapabilities> {
    this.capabilities = buildCapabilities(this.snapshot);
    return this.capabilities;
  }

  // ---- Commands -----------------------------------------------------------
  async submitCommand(request: RuntimeCommandRequest): Promise<CommandAccepted> {
    // Idempotency guard.
    const existing = commandStore.findActiveByIdempotency(request.idempotencyKey);
    if (existing) {
      const receipt = {
        commandId: existing.commandId,
        clientRequestId: existing.clientRequestId,
        correlationId: existing.correlationId,
        state: "ACCEPTED" as const,
        acceptedAt: existing.createdAt,
        receivedAt: existing.createdAt,
        idempotencyKey: existing.idempotencyKey,
      };
      return receipt;
    }

    const commandId = `cmd_${safeUuid()}`;
    commandStore.create(commandId, request);
    const acceptedAt = new Date().toISOString();

    // Async lifecycle simulation.
    void this.simulateLifecycle(commandId, request);
    this.notifyCommand(commandId);

    const receipt = {
      commandId,
      clientRequestId: request.clientRequestId,
      correlationId: request.correlationId,
      state: "ACCEPTED" as const,
      acceptedAt,
      receivedAt: acceptedAt,
      idempotencyKey: request.idempotencyKey,
    };
    return receipt;
  }

  private async simulateLifecycle(commandId: string, request: RuntimeCommandRequest) {
    const scen = this.scenario;
    const isTradingCmd =
      request.kind.startsWith("order.") ||
      request.kind.startsWith("position.") ||
      request.kind === "runtime.emergencyKill";

    // Scenario-driven outcomes for trading commands.
    const forceUnknown = scen === "executionUnknown" && isTradingCmd;
    const forceFailure = scen === "brokerDown" && isTradingCmd;

    await sleep(180);
    commandStore.update(commandId, { state: "ACCEPTED", currentStep: "Runtime accepted request" });
    this.notifyCommand(commandId);
    this.emitEvent("command.accepted", { commandId, kind: request.kind }, request.correlationId);

    await sleep(320);
    commandStore.update(commandId, {
      state: "ACKNOWLEDGED",
      currentStep: "Runtime acknowledged",
      progress: 0.2,
    });
    this.notifyCommand(commandId);

    await sleep(400);
    commandStore.update(commandId, {
      state: "IN_PROGRESS",
      currentStep: isTradingCmd
        ? "Broker gateway forwarded request"
        : "Applying runtime transition",
      progress: 0.55,
    });
    this.notifyCommand(commandId);

    await sleep(700);

    if (forceFailure) {
      commandStore.update(commandId, {
        state: "FAILED",
        currentStep: "Broker rejected request",
        progress: 1,
        errorCode: "BROKER_DISCONNECTED",
        errorMessage: "Broker gateway is not connected. Reconnect required.",
      });
      this.notifyCommand(commandId);
      this.emitEvent("command.failed", { commandId }, request.correlationId);
      return;
    }
    if (forceUnknown) {
      commandStore.update(commandId, {
        state: "EXECUTION_UNKNOWN",
        currentStep: "Broker response timed out",
        progress: 1,
        errorCode: "EXECUTION_UNKNOWN",
        errorMessage:
          "The broker may have accepted or completed this operation. Do not retry until reconciliation confirms broker state.",
      });
      this.notifyCommand(commandId);
      this.emitEvent("command.execution_unknown", { commandId }, request.correlationId);
      return;
    }

    commandStore.update(commandId, {
      state: "COMPLETED",
      currentStep: "Runtime confirmed completion",
      progress: 1,
      message: `Mock runtime completed ${request.kind}. No live broker execution occurred.`,
    });
    this.notifyCommand(commandId);
    this.emitEvent("command.completed", { commandId }, request.correlationId);
  }

  async getCommand(commandId: string): Promise<RuntimeCommandStatus> {
    const c = commandStore.get(commandId);
    if (!c) throw new Error(`Unknown command ${commandId}`);
    return c;
  }

  subscribeCommand(commandId: string, listener: (s: RuntimeCommandStatus) => void): () => void {
    let set = this.commandListeners.get(commandId);
    if (!set) {
      set = new Set();
      this.commandListeners.set(commandId, set);
    }
    set.add(listener);
    // Also push current state through the general store subscription.
    return () => {
      set!.delete(listener);
      if (set!.size === 0) this.commandListeners.delete(commandId);
    };
  }

  // ---- Trade history ------------------------------------------------------
  async getTradeHistory(query?: TradeHistoryQuery): Promise<TradeHistoryPage> {
    return getFixtureTradeHistory(query?.cursor ?? null, query?.limit ?? 25);
  }

  private notifyCommand(commandId: string) {
    const status = commandStore.get(commandId);
    if (!status) return;
    const set = this.commandListeners.get(commandId);
    if (!set) return;
    for (const l of set) l(status);
  }

  // ---- Connection ---------------------------------------------------------
  getConnectionState(): RuntimeConnectionStateSnapshot {
    return this.connection;
  }
  subscribeConnection(listener: (s: RuntimeConnectionStateSnapshot) => void): () => void {
    this.connectionListeners.add(listener);
    return () => {
      this.connectionListeners.delete(listener);
    };
  }

  // ---- Operator -----------------------------------------------------------
  getOperator(): OperatorIdentity {
    return this.operator;
  }

  // ---- Meta ---------------------------------------------------------------
  getDescriptor(): RuntimeAdapterDescriptor {
    return {
      adapterType: "DEVELOPMENT_FIXTURE",
      dataSource: "DEVELOPMENT_FIXTURE",
      isDevelopmentOnly: true,
    };
  }
  isDevelopmentFixture(): boolean {
    return true;
  }
  /** @deprecated Use isDevelopmentFixture(). */
  isDemo(): boolean {
    return this.isDevelopmentFixture();
  }
  /** @deprecated Use isDevelopmentFixture(). */
  isFixture(): boolean {
    return this.isDevelopmentFixture();
  }

  // ---- Demo controls ------------------------------------------------------
  setScenario(scenario: ScenarioKey): void {
    if (scenario === this.scenario) return;
    this.scenario = scenario;
    this.snapshot = buildSnapshot(scenario);
    this.revision += 1;
    this.sequence += 1;
    this.capabilities = buildCapabilities(this.snapshot);

    // Simulate a boot change when scenario transitions to "killed" and back to "healthy".
    if (scenario === "healthy") {
      bootCounter += 1;
    }

    // Adjust connection state to mirror scenario.
    const brokerDown = scenario === "brokerDown";
    this.connection = {
      ...this.connection,
      state: brokerDown ? "STALE" : "CONNECTED",
      lastMessageAt: new Date().toISOString(),
      lastHeartbeatAt: new Date().toISOString(),
      dataAgeMs: brokerDown ? 12000 : 0,
    };
    for (const l of this.connectionListeners) l(this.connection);

    this.emitSnapshot();
  }

  getScenario(): ScenarioKey {
    return this.scenario;
  }

}

function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

/** Preferred name. `MockRuntimeAdapter` is retained as a deprecated alias. */
export { MockRuntimeAdapter as DevelopmentFixtureAdapter };
