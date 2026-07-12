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
