// Development Fixture Event Source — deterministic, developer-controllable.
// Emits envelopes clearly labeled as DEVELOPMENT_FIXTURE.

import { useSyncExternalStore } from "react";
import type {
  EventSeverity,
  EventSourceState,
  RuntimeEventEnvelope,
  RuntimeEventType,
} from "./event-types";
import type { RuntimeEventSource } from "./event-source";

const DEFAULT_TICK_MS = 3500;

let nextEid = 1;
let seq = 1;

function eid(prefix = "evt") {
  return `${prefix}-${Date.now().toString(36)}-${(nextEid++).toString(36)}`;
}

interface EmitOptions {
  type: RuntimeEventType;
  severity?: EventSeverity;
  payload?: Record<string, unknown>;
  correlationId?: string;
  commandId?: string;
  orderId?: string;
  positionId?: string;
  strategyId?: string;
  incidentId?: string;
  reconciliationRunId?: string;
  /** Override the auto-incremented sequence (developer scenarios). */
  sequenceOverride?: number;
  /** Override the boot id (simulating old boot / restart). */
  bootIdOverride?: string;
  /** Force a duplicate eventId (for dedup testing). */
  eventIdOverride?: string;
}

type Listener = (env: RuntimeEventEnvelope) => void;
type StateListener = () => void;

export class DevelopmentFixtureEventSource implements RuntimeEventSource {
  readonly kind = "fixture" as const;

  private state: EventSourceState = "STOPPED";
  private paused = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private tickMs = DEFAULT_TICK_MS;
  private bootId = `boot-${Date.now().toString(36)}`;
  private runtimeId = "xdirga-runtime-fixture";
  private revision = 1;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<StateListener>();

  async start() {
    if (this.state === "RUNNING") return;
    this.state = "STARTING";
    this.notifyState();
    this.timer = setInterval(() => this.tick(), this.tickMs);
    this.state = "RUNNING";
    this.notifyState();
  }

  async stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.state = "STOPPED";
    this.notifyState();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeState(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  getState(): EventSourceState {
    return this.state;
  }

  isPaused = () => this.paused;

  setPaused(paused: boolean) {
    this.paused = paused;
    this.notifyState();
  }

  setTickMs(ms: number) {
    this.tickMs = Math.max(500, ms);
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = setInterval(() => this.tick(), this.tickMs);
    }
  }

  // ---------------------------------------------------------------------------
  // Deterministic scenario emitters
  // ---------------------------------------------------------------------------

  emit(options: EmitOptions): RuntimeEventEnvelope {
    const now = new Date().toISOString();
    const env: RuntimeEventEnvelope = {
      eventId: options.eventIdOverride ?? eid(),
      type: options.type,
      runtimeId: this.runtimeId,
      bootId: options.bootIdOverride ?? this.bootId,
      revision: this.revision++,
      sequence: options.sequenceOverride ?? seq++,
      occurredAt: now,
      emittedAt: now,
      receivedAt: now,
      severity: options.severity ?? "INFO",
      source: "DEVELOPMENT_FIXTURE",
      correlationId: options.correlationId,
      commandId: options.commandId,
      orderId: options.orderId,
      positionId: options.positionId,
      strategyId: options.strategyId,
      incidentId: options.incidentId,
      reconciliationRunId: options.reconciliationRunId,
      payload: options.payload ?? {},
    };
    this.dispatch(env);
    return env;
  }

  emitBurst(count = 8) {
    for (let i = 0; i < count; i++) {
      this.emit({
        type: "runtime.health.changed",
        severity: "INFO",
        payload: { index: i, note: "burst" },
      });
    }
  }

  emitDuplicate() {
    const env = this.emit({ type: "broker.request.completed", severity: "INFO", payload: { latencyMs: 42 } });
    // Re-dispatch same eventId + sequence.
    this.dispatch({ ...env, receivedAt: new Date().toISOString() });
  }

  emitOutOfOrder() {
    const older = { ...this.buildEnvelope("runtime.health.changed", "INFO", {}), sequence: Math.max(1, seq - 5) };
    this.dispatch(older);
  }

  emitSequenceGap(gap = 5) {
    seq += gap;
    this.emit({
      type: "runtime.health.changed",
      severity: "WARNING",
      payload: { note: "gap-injected" },
    });
  }

  emitOldBoot() {
    this.emit({
      type: "runtime.state.changed",
      severity: "WARNING",
      bootIdOverride: "boot-000000",
      payload: { note: "old-boot" },
    });
  }

  emitInvalidPayload() {
    // Deliberately violate the payload shape for command.*
    this.dispatch({
      ...this.buildEnvelope("command.completed", "INFO", { totallyWrong: true }),
    });
  }

  emitCriticalScenario() {
    this.emit({
      type: "safety.circuit_breaker.opened",
      severity: "CRITICAL",
      payload: { key: "daily-loss", reason: "Simulated fixture breaker" },
    });
    this.emit({
      type: "position.unprotected",
      severity: "CRITICAL",
      positionId: "fx-pos-99",
      payload: { positionId: "fx-pos-99", protection: "UNPROTECTED", symbol: "XAUUSD" },
    });
    this.emit({
      type: "command.execution_unknown",
      severity: "CRITICAL",
      commandId: "cmd-fixture-eu",
      payload: { commandId: "cmd-fixture-eu", reason: "Broker did not acknowledge within window" },
    });
  }

  rotateBootId() {
    this.bootId = `boot-${Date.now().toString(36)}`;
    seq = 1;
    this.emit({
      type: "runtime.state.changed",
      severity: "INFO",
      payload: { note: "boot-rotated", newBootId: this.bootId },
    });
  }

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------

  private tick() {
    if (this.paused) return;
    const roll = Math.random();
    if (roll < 0.55) {
      this.emit({ type: "broker.request.completed", severity: "INFO", payload: { latencyMs: 30 + Math.round(Math.random() * 40) } });
    } else if (roll < 0.75) {
      this.emit({ type: "strategy.signal.generated", severity: "DEBUG", strategyId: "trend-v2", payload: { strategyId: "trend-v2", confidence: Math.round(Math.random() * 100) / 100 } });
    } else if (roll < 0.88) {
      this.emit({ type: "runtime.health.changed", severity: "INFO", payload: { subsystem: "market-data", state: "OK" } });
    } else if (roll < 0.95) {
      this.emit({ type: "risk.limit.warning", severity: "WARNING", payload: { key: "daily-loss", value: 0.6, threshold: 0.75 } });
    } else {
      this.emit({
        type: "position.protection_changed",
        severity: "WARNING",
        positionId: "fx-pos-42",
        payload: { positionId: "fx-pos-42", protection: "PARTIALLY_PROTECTED", symbol: "EURUSD" },
      });
    }
  }

  private buildEnvelope(
    type: RuntimeEventType,
    severity: EventSeverity,
    payload: Record<string, unknown>,
  ): RuntimeEventEnvelope {
    const now = new Date().toISOString();
    return {
      eventId: eid(),
      type,
      runtimeId: this.runtimeId,
      bootId: this.bootId,
      revision: this.revision++,
      sequence: seq++,
      occurredAt: now,
      emittedAt: now,
      receivedAt: now,
      severity,
      source: "DEVELOPMENT_FIXTURE",
      payload,
    };
  }

  private dispatch(env: RuntimeEventEnvelope) {
    for (const l of this.listeners) l(env);
  }

  private notifyState() {
    for (const l of this.stateListeners) l();
  }
}

// -----------------------------------------------------------------------------
// Singleton + React hook
// -----------------------------------------------------------------------------

let singleton: DevelopmentFixtureEventSource | null = null;
export function getFixtureEventSource(): DevelopmentFixtureEventSource {
  if (!singleton) singleton = new DevelopmentFixtureEventSource();
  return singleton;
}

export function useFixtureEventSourceState() {
  const src = getFixtureEventSource();
  return useSyncExternalStore(
    (l) => src.subscribeState(l),
    () => ({ state: src.getState(), paused: src.isPaused() }),
    () => ({ state: "STOPPED" as EventSourceState, paused: false }),
  );
}

// -----------------------------------------------------------------------------
// Autopilot management lifecycle (demo)
//
// Emits a deterministic sequence of `position.management.*` events against a
// fixture FX position so the autopilot panel visibly evolves during a demo
// session: BE armed → BE applied → 2 trailing moves → partial TP #1 executed.
// Safe to call multiple times; each call uses a fresh planId + positionId
// suffix so the event stream stays unique.
// -----------------------------------------------------------------------------

export function scheduleFixtureManagementLifecycle(options?: {
  positionId?: string;
  symbol?: string;
  entryPrice?: number;
  stepMs?: number;
}) {
  const src = getFixtureEventSource();
  const positionId = options?.positionId ?? "fx-pos-42";
  const symbol = options?.symbol ?? "EURUSD";
  const entry = options?.entryPrice ?? 1.0850;
  const stepMs = options?.stepMs ?? 4500;
  const planId = `plan-${Date.now().toString(36)}`;

  const level1 = {
    levelId: "tp-1",
    atR: 1,
    closePercent: 50,
    state: "PENDING" as const,
    executedAt: null,
    executedPrice: null,
    closedVolume: null,
  };
  const level2 = { ...level1, levelId: "tp-2", atR: 2, closePercent: 30 };

  const initialPlan = {
    planId,
    source: "STRATEGY" as const,
    breakEven: {
      enabled: true,
      triggerR: 1,
      offsetPoints: 2,
      state: "PENDING" as const,
      appliedAt: null,
    },
    trailing: {
      mode: "STEP" as const,
      active: false,
      distancePoints: 120,
      currentStopPrice: null,
      lastMovedAt: null,
      moveCount: 0,
    },
    partialTp: { levels: [level1, level2] },
    timeExit: { maxHoldUntil: null, state: "PENDING" as const },
    nextAction: "Arm break-even at 1R",
    lastError: null,
    paused: false,
  };

  // Step 0: plan installed.
  src.emit({
    type: "position.management.plan_changed",
    severity: "INFO",
    positionId,
    payload: { positionId, plan: initialPlan, symbol },
  });

  // Step 1: BE applied.
  setTimeout(() => {
    src.emit({
      type: "position.management.action_executed",
      severity: "INFO",
      positionId,
      payload: { positionId, planId, action: "BREAK_EVEN", detail: { appliedAt: new Date().toISOString() } },
    });
  }, stepMs);

  // Step 2 & 3: trailing moves.
  setTimeout(() => {
    src.emit({
      type: "position.management.action_executed",
      severity: "INFO",
      positionId,
      payload: { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: +(entry + 0.0012).toFixed(5) } },
    });
  }, stepMs * 2);

  setTimeout(() => {
    src.emit({
      type: "position.management.action_executed",
      severity: "INFO",
      positionId,
      payload: { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: +(entry + 0.0024).toFixed(5) } },
    });
  }, stepMs * 3);

  // Step 4: partial TP #1 executed.
  setTimeout(() => {
    src.emit({
      type: "position.management.action_executed",
      severity: "INFO",
      positionId,
      payload: {
        positionId,
        planId,
        action: "PARTIAL_TP",
        detail: { levelId: "tp-1", executedPrice: +(entry + 0.0030).toFixed(5), closedVolume: 0.5 },
      },
    });
  }, stepMs * 4);

  return { planId, positionId };
}

