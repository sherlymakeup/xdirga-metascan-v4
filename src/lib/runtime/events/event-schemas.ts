// Zod schemas for runtime event validation.
// Envelope is strictly validated against the authoritative event catalog;
// unknown event types are rejected. Payload is validated best-effort per type.

import { z } from "zod";
import type { RuntimeEventEnvelope, EventSeverity } from "./runtime-event-envelope";
import {
  runtimeEventTypeSchema,
  eventSeveritySchema,
  frontendDataSourceSchema,
} from "./runtime-event-envelope";

const nonNegativeInt = z.number().int().nonnegative();
const timestamp = z.string().datetime();

export const handshakeSchema = z.object({
  runtimeName: z.string().min(1), runtimeVersion: z.string().min(1), runtimeId: z.string().min(1), bootId: z.string().min(1),
  protocolId: z.string().min(1), protocolVersion: z.string().min(1), schemaVersion: z.string().min(1), schemaHash: z.string().min(1),
  capabilitiesRevision: nonNegativeInt, minFrontendVersion: z.string().optional(), frontendVersion: z.string().optional(),
  supportedFeatures: z.array(z.string()), supportedCommands: z.array(z.string()), brokerProvider: z.literal("EXNESS"),
  brokerEnvironment: z.enum(["TRIAL", "LIVE"]), executionSemantics: z.literal("LIVE"), source: z.literal("LOCAL_RUNTIME"), observedAt: timestamp,
}).passthrough();

const text = z.string();
const numberOrNull = z.number().nullable();
const timeOrNull = timestamp.nullable();
const runtimeState = z.enum(["DISCONNECTED", "INITIALIZING", "DEGRADED", "RECONNECTING", "RECONCILING", "READY", "PAUSED", "STOPPING", "STOPPED", "ERROR", "KILLED"]);
const severity = z.enum(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]);
const freshness = z.enum(["FRESH", "DELAYED", "STALE", "UNAVAILABLE"]);
const orderSide = z.enum(["BUY", "SELL"]);
const management = z.object({
  planId: text, source: z.enum(["STRATEGY", "MANUAL_OVERRIDE"]),
  breakEven: z.object({ enabled: z.boolean(), triggerR: z.number(), offsetPoints: z.number(), state: z.enum(["PENDING", "APPLIED", "SKIPPED"]), appliedAt: timeOrNull }),
  trailing: z.object({ mode: z.enum(["OFF", "FIXED_POINTS", "ATR", "STEP", "STRUCTURE"]), active: z.boolean(), distancePoints: numberOrNull, currentStopPrice: numberOrNull, lastMovedAt: timeOrNull, moveCount: nonNegativeInt }),
  partialTp: z.object({ levels: z.array(z.object({ levelId: text, atR: z.number(), closePercent: z.number(), state: z.enum(["PENDING", "EXECUTED", "SKIPPED", "FAILED"]), executedAt: timeOrNull, executedPrice: numberOrNull, closedVolume: numberOrNull })) }),
  timeExit: z.object({ maxHoldUntil: timeOrNull, state: z.enum(["PENDING", "EXECUTED", "DISABLED"]) }), nextAction: text.nullable(), lastError: text.nullable(), paused: z.boolean(),
});
const cockpitSnapshotSchema = z.object({
  positionsAvailable: z.boolean(), positionsSourceFrameId: numberOrNull, positionsObservedAt: timeOrNull, accountAvailable: z.boolean(), accountSourceFrameId: numberOrNull, accountObservedAt: timeOrNull,
  runtime: z.object({ id: text, sessionId: text, version: text, buildHash: text, environment: z.literal("LOCAL"), tradingMode: z.enum(["TRIAL", "LIVE"]), state: runtimeState, previousState: runtimeState, stateChangedAt: timeOrNull, stateReason: text, startedAt: timeOrNull, uptimeSec: numberOrNull, lastHeartbeatAt: timeOrNull, heartbeatLatencyMs: numberOrNull, entriesEnabled: z.boolean(), automationEnabled: z.boolean(), hostname: text, os: text, pid: z.number() }),
  subsystems: z.array(z.object({ key: text, label: text, state: z.enum(["OK", "DEGRADED", "DOWN", "UNKNOWN"]), lastHeartbeatAt: timestamp, latencyMs: numberOrNull, restartCount: z.number(), currentAction: text.nullable(), lastError: text.nullable() })),
  broker: z.object({ broker: text, server: text, loginMasked: text, accountMode: z.enum(["TRIAL", "LIVE"]), connection: z.enum(["CONNECTED", "DISCONNECTED", "RECONNECTING", "DEGRADED", "UNKNOWN"]), tradingPermitted: z.boolean(), terminalVersion: text, lastTickAt: timeOrNull, lastRequestAt: timeOrNull, queueDepth: z.number(), avgLatencyMs: numberOrNull, timeoutCount: z.number(), reconnectAttempts: z.number() }),
  account: z.object({ currency: text, balance: numberOrNull, equity: numberOrNull, margin: numberOrNull, freeMargin: numberOrNull, marginLevel: numberOrNull, floatingPnl: numberOrNull, realizedPnlToday: numberOrNull, realizedPnlWeek: numberOrNull, dailyDrawdown: numberOrNull, maxDrawdown: numberOrNull, grossExposure: numberOrNull, netExposure: numberOrNull, openPositions: numberOrNull, pendingOrders: numberOrNull, tradesToday: numberOrNull, winRate: numberOrNull, profitFactor: numberOrNull, riskUtilization: numberOrNull, updatedAt: timeOrNull, freshness }),
  strategies: z.array(z.object({ id: text, name: text, version: text, symbols: z.array(text), timeframe: text, status: z.enum(["DISABLED", "IDLE", "WARMING_UP", "ACTIVE", "PAUSED", "BLOCKED", "DEGRADED", "ERROR"]), tradingMode: z.enum(["TRIAL", "LIVE"]), entriesEnabled: z.boolean(), allocationPct: z.number(), pnlToday: z.number(), drawdown: z.number(), signalsToday: z.number(), lastSignalAt: timeOrNull, lastExecutionAt: timeOrNull, currentBias: z.enum(["LONG", "SHORT", "FLAT"]), confidence: z.number(), openPositions: z.number(), health: z.enum(["OK", "DEGRADED", "ERROR"]) })),
  positions: z.array(z.object({ id: text, brokerTicket: text, ownership: z.enum(["BOT_MANAGED", "FOREIGN", "UNKNOWN"]), dataAvailable: z.boolean(), sourceFrameId: z.number(), observedAt: timeOrNull, symbol: text, side: orderSide, volume: z.number(), entryPrice: z.number(), currentPrice: z.number(), stopLoss: numberOrNull, takeProfit: numberOrNull, floatingPnl: z.number(), realizedPnl: numberOrNull, riskAmount: numberOrNull, riskPct: numberOrNull, openedAt: timeOrNull, strategy: text.nullable(), protection: z.enum(["PROTECTED", "PARTIALLY_PROTECTED", "UNPROTECTED", "INVALID_PROTECTION", "UNKNOWN"]), state: z.enum(["OPEN", "CLOSING", "CLOSED", "RECONCILE_REQUIRED"]), rMultiple: numberOrNull, mfe: numberOrNull, mae: numberOrNull, commission: z.number(), swap: z.number(), netPnl: z.number(), management: management.nullable() })),
  orders: z.array(z.object({ id: text, brokerTicket: text.nullable(), clientRequestId: text, correlationId: text, symbol: text, side: orderSide, type: z.enum(["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]), volume: z.number(), requestedPrice: numberOrNull, filledPrice: numberOrNull, stopLoss: numberOrNull, takeProfit: numberOrNull, slippage: numberOrNull, strategy: text, createdAt: timestamp, updatedAt: timestamp, status: z.enum(["CREATED", "VALIDATED", "RISK_CHECKED", "SAFETY_CHECKED", "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "TIMED_OUT", "EXECUTION_UNKNOWN", "RECONCILED"]), rejectionReason: text.nullable(), lifecycle: z.array(z.object({ at: timestamp, step: z.enum(["CREATED", "VALIDATED", "RISK_CHECKED", "SAFETY_CHECKED", "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "TIMED_OUT", "EXECUTION_UNKNOWN", "RECONCILED", "BROKER_ACK", "OPERATOR", "SYSTEM"]), detail: text, latencyMs: z.number().optional() })) })),
  markets: z.array(z.object({ symbol: text, group: z.enum(["FX", "METALS", "INDICES", "CRYPTO"]).nullable(), bid: z.number(), ask: z.number(), spread: z.number(), last: z.number(), changePct: numberOrNull, sessionOpen: z.boolean().nullable(), tradingPermitted: z.boolean(), tickAgeMs: z.number(), freshness, contractSize: z.number(), tickSize: z.number(), minVolume: z.number(), maxVolume: z.number(), volumeStep: z.number(), swapLong: numberOrNull, swapShort: numberOrNull, marginRequirement: numberOrNull })),
  alerts: z.array(z.object({ id: text, severity, title: text, source: text, createdAt: timestamp, description: text, suggestedAction: text, acknowledged: z.boolean(), incidentId: text.optional() })),
  incidents: z.array(z.object({ id: text, severity, status: z.enum(["OPEN", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATED", "RESOLVED"]), title: text, startedAt: timestamp, durationSec: z.number(), source: text, impact: text, affectedComponents: z.array(text), rootCause: text.nullable(), resolution: text.nullable() })),
  riskLimits: z.array(z.object({ key: text, label: text, configured: z.number(), current: z.number(), unit: z.enum(["PCT", "USD", "COUNT", "MS", "PRICE"]), warnAt: z.number(), breachAt: z.number(), breached: z.boolean(), changedAt: timestamp, changedBy: text })),
  breakers: z.array(z.object({ key: text, label: text, state: z.enum(["CLOSED", "WARNING", "OPEN", "RECOVERING", "MANUAL_LOCK"]), triggerCondition: text, currentValue: text, threshold: text, triggeredAt: timeOrNull, recoveryCondition: text, manualResetAllowed: z.boolean(), lastResetAt: timeOrNull })),
  reconciliation: z.object({ state: z.enum(["IDLE", "RUNNING", "OK", "ISSUES", "FAILED"]), lastRunAt: timeOrNull, brokerOrders: z.number(), runtimeOrders: z.number(), brokerPositions: z.number(), runtimePositions: z.number(), missingOrders: z.number(), unknownOrders: z.number(), positionMismatches: z.number(), volumeMismatches: z.number(), stateMismatches: z.number(), issues: z.array(z.object({ entity: z.enum(["ORDER", "POSITION"]), entityId: text, runtimeState: text, brokerState: text, difference: text, severity, suggestedAction: text, resolved: z.boolean() })) }),
  events: z.array(z.object({ id: text, at: timestamp, severity: z.enum(["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]), source: text, component: text, message: text, correlationId: text.optional(), orderId: text.optional(), positionId: text.optional(), strategy: text.optional(), symbol: text.optional(), payload: z.record(z.unknown()).optional() })),
  equityCurve: z.array(z.object({ at: timestamp, equity: z.number(), balance: z.number(), floatingPnl: z.number(), drawdown: z.number() })),
});
export const snapshotSchema = z.object({
  metadata: z.object({ runtimeId: text, bootId: text, revision: nonNegativeInt, sequence: nonNegativeInt, generatedAt: timestamp, serverTimestamp: timestamp, protocolId: text, protocolVersion: text, schemaVersion: text, schemaHash: text, source: z.literal("LOCAL_RUNTIME") }).strict(),
  snapshot: cockpitSnapshotSchema,
}).passthrough();

export const envelopeSchema = z.object({
  eventId: z.string().min(1),
  type: runtimeEventTypeSchema,
  runtimeId: z.string().min(1),
  bootId: z.string().min(1),
  revision: z.number().int().nonnegative(),
  sequence: z.number().int().nonnegative(),
  occurredAt: z.string().min(1),
  emittedAt: z.string().min(1),
  receivedAt: z.string().min(1),
  severity: eventSeveritySchema,
  source: frontendDataSourceSchema,
  correlationId: z.string().optional(),
  commandId: z.string().optional(),
  orderId: z.string().optional(),
  positionId: z.string().optional(),
  strategyId: z.string().optional(),
  incidentId: z.string().optional(),
  reconciliationRunId: z.string().optional(),
  payload: z.unknown(),
});

// -----------------------------------------------------------------------------
// Position autopilot management — schema factories exposed for direct testing.
// -----------------------------------------------------------------------------

export const MANAGEMENT_ACTIONS = [
  "BREAK_EVEN",
  "TRAILING_MOVE",
  "PARTIAL_TP",
  "TIME_EXIT",
] as const;
export const managementActionSchema = z.enum(MANAGEMENT_ACTIONS);

const managementPlanSchema = z.object({
  planId: z.string().min(1),
  source: z.enum(["STRATEGY", "MANUAL_OVERRIDE"]),
  breakEven: z.object({
    enabled: z.boolean(),
    triggerR: z.number(),
    offsetPoints: z.number(),
    state: z.enum(["PENDING", "APPLIED", "SKIPPED"]),
    appliedAt: z.string().nullable(),
  }).passthrough(),
  trailing: z.object({
    mode: z.enum(["OFF", "FIXED_POINTS", "ATR", "STEP", "STRUCTURE"]),
    active: z.boolean(),
    distancePoints: z.number().nullable(),
    currentStopPrice: z.number().nullable(),
    lastMovedAt: z.string().nullable(),
    moveCount: z.number().int().nonnegative(),
  }).passthrough(),
  partialTp: z.object({
    levels: z.array(z.object({
      levelId: z.string().min(1),
      atR: z.number(),
      closePercent: z.number(),
      state: z.enum(["PENDING", "EXECUTED", "SKIPPED", "FAILED"]),
      executedAt: z.string().nullable(),
      executedPrice: z.number().nullable(),
      closedVolume: z.number().nullable(),
    }).passthrough()),
  }).passthrough(),
  timeExit: z.object({
    maxHoldUntil: z.string().nullable(),
    state: z.enum(["PENDING", "EXECUTED", "DISABLED"]),
  }).passthrough(),
  nextAction: z.string().nullable(),
  lastError: z.string().nullable(),
  paused: z.boolean(),
}).passthrough();

export function planChangedPayloadSchema() {
  return z.object({
    positionId: z.string().min(1),
    plan: managementPlanSchema,
  }).passthrough();
}

const breakEvenDetail = z.object({ appliedAt: z.string().optional() }).passthrough();
const trailingMoveDetail = z.object({ newStopPrice: z.number() }).passthrough();
const partialTpDetail = z.object({
  levelId: z.string().min(1),
  executedPrice: z.number(),
  closedVolume: z.number(),
}).passthrough();
const timeExitDetail = z.object({ executedAt: z.string().optional() }).passthrough();

export function actionExecutedPayloadSchema() {
  const base = { positionId: z.string().min(1), planId: z.string().min(1) };
  return z.discriminatedUnion("action", [
    z.object({ ...base, action: z.literal("BREAK_EVEN"), detail: breakEvenDetail.optional() }).passthrough(),
    z.object({ ...base, action: z.literal("TRAILING_MOVE"), detail: trailingMoveDetail }).passthrough(),
    z.object({ ...base, action: z.literal("PARTIAL_TP"), detail: partialTpDetail }).passthrough(),
    z.object({ ...base, action: z.literal("TIME_EXIT"), detail: timeExitDetail.optional() }).passthrough(),
  ]);
}

export function actionFailedPayloadSchema() {
  return z.object({
    positionId: z.string().min(1),
    planId: z.string().min(1),
    action: managementActionSchema,
    reason: z.string().min(1),
    retryable: z.boolean(),
    levelId: z.string().optional(),
  }).passthrough();
}

/**
 * Payload schemas by prefix. Kept permissive on purpose — the goal is to
 * reject clearly malformed payloads without coupling every UI to backend
 * schema shape churn.
 */
const payloadShapes: Array<[RegExp, z.ZodTypeAny]> = [
  [/^command\./, z.object({ commandId: z.string(), state: z.string().optional(), message: z.string().optional(), reason: z.string().optional() }).passthrough()],
  [/^order\./, z.object({ orderId: z.string(), status: z.string().optional(), symbol: z.string().optional() }).passthrough()],

  // ---------------------------------------------------------------------------
  // Position management (autopilot) — three DISTINCT payload schemas.
  //
  // Action enum spelling is authoritative and must match HANDOFF.md §10:
  //   BREAK_EVEN | TRAILING_MOVE | PARTIAL_TP | TIME_EXIT
  //
  // plan_changed  → carries the full PositionManagement plan under `plan`.
  //                  Also used to broadcast pause/resume (paused: bool flipped).
  // action_executed → action-specific detail (see per-action shapes below).
  // action_failed → reason + retryable flag; `levelId` when PARTIAL_TP.
  // ---------------------------------------------------------------------------
  [/^position\.management\.plan_changed$/, planChangedPayloadSchema()],
  [/^position\.management\.action_executed$/, actionExecutedPayloadSchema()],
  [/^position\.management\.action_failed$/, actionFailedPayloadSchema()],

  [/^position\./, z.object({ positionId: z.string(), protection: z.string().optional(), symbol: z.string().optional() }).passthrough()],

  // Closed-trade payload. Sign convention: netPnl === grossPnl + commission + swap.
  [/^trade\.closed$/, z.object({
    tradeId: z.string(),
    positionId: z.string(),
    strategyId: z.string(),
    symbol: z.string(),
    grossPnl: z.number(),
    commission: z.number(),
    swap: z.number(),
    netPnl: z.number(),
    rMultiple: z.number().nullable(),
    exitReason: z.string(),
  }).passthrough()],

  [/^strategy\./, z.object({ strategyId: z.string() }).passthrough()],
  [/^safety\.circuit_breaker\./, z.object({ key: z.string(), state: z.string().optional() }).passthrough()],
  [/^reconciliation\./, z.object({ reconciliationRunId: z.string().optional() }).passthrough()],
  [/^risk\.limit\./, z.object({ key: z.string(), value: z.number().optional(), threshold: z.number().optional() }).passthrough()],
  [/^system\.event_gap\./, z.object({ from: z.number(), to: z.number(), missing: z.number() }).passthrough()],
];

export function validateHandshake(raw: unknown) {
  const parsed = handshakeSchema.safeParse(raw);
  return parsed.success ? { ok: true as const, handshake: parsed.data } : { ok: false as const };
}

export function validateSnapshot(raw: unknown) {
  const parsed = snapshotSchema.safeParse(raw);
  return parsed.success ? { ok: true as const, snapshot: parsed.data } : { ok: false as const };
}

export interface EnvelopeValidation {
  ok: boolean;
  envelope?: RuntimeEventEnvelope;
  errors?: string[];
}

export function validateEnvelope(raw: unknown): EnvelopeValidation {
  const parsed = envelopeSchema.safeParse(raw);
  if (!parsed.success) {
    return { ok: false, errors: parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`) };
  }
  const env = parsed.data as RuntimeEventEnvelope;
  const shape = payloadShapes.find(([re]) => re.test(env.type))?.[1];
  if (shape) {
    const inner = shape.safeParse(env.payload);
    if (!inner.success) {
      return {
        ok: false,
        errors: inner.error.issues.map((i) => `payload.${i.path.join(".")}: ${i.message}`),
      };
    }
  }
  return { ok: true, envelope: env };
}

export const SEVERITY_VALUES: readonly EventSeverity[] = eventSeveritySchema.options;
