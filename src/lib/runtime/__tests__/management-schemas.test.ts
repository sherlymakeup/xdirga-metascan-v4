// Phase 5F.5 — distinct Zod payload schemas for position.management.* events.
// Verifies action enum spelling, discriminated union on action, and required
// per-action fields.

import { describe, it, expect } from "vitest";
import {
  planChangedPayloadSchema,
  actionExecutedPayloadSchema,
  actionFailedPayloadSchema,
  MANAGEMENT_ACTIONS,
} from "../events/event-schemas";

const validPlan = {
  planId: "plan-1",
  source: "STRATEGY",
  breakEven: { enabled: true, triggerR: 1, offsetPoints: 2, state: "PENDING", appliedAt: null },
  trailing: { mode: "STEP", active: false, distancePoints: 100, currentStopPrice: null, lastMovedAt: null, moveCount: 0 },
  partialTp: { levels: [{ levelId: "tp-1", atR: 1, closePercent: 50, state: "PENDING", executedAt: null, executedPrice: null, closedVolume: null }] },
  timeExit: { maxHoldUntil: null, state: "PENDING" },
  nextAction: null,
  lastError: null,
  paused: false,
};

describe("management action enum", () => {
  it("preserves the authoritative spelling", () => {
    expect([...MANAGEMENT_ACTIONS]).toEqual([
      "BREAK_EVEN",
      "TRAILING_MOVE",
      "PARTIAL_TP",
      "TIME_EXIT",
    ]);
  });
});

describe("plan_changed payload schema", () => {
  const schema = planChangedPayloadSchema();

  it("accepts a valid full-plan payload", () => {
    const res = schema.safeParse({ positionId: "pos-1", plan: validPlan });
    expect(res.success).toBe(true);
  });

  it("rejects a payload without a plan", () => {
    const res = schema.safeParse({ positionId: "pos-1" });
    expect(res.success).toBe(false);
  });

  it("rejects a payload without positionId", () => {
    const res = schema.safeParse({ plan: validPlan });
    expect(res.success).toBe(false);
  });
});

describe("action_executed payload schema", () => {
  const schema = actionExecutedPayloadSchema();
  const base = { positionId: "pos-1", planId: "plan-1" };

  it("accepts BREAK_EVEN with optional detail", () => {
    expect(schema.safeParse({ ...base, action: "BREAK_EVEN" }).success).toBe(true);
    expect(schema.safeParse({ ...base, action: "BREAK_EVEN", detail: { appliedAt: "2026-07-12T00:00:00Z" } }).success).toBe(true);
  });

  it("REQUIRES newStopPrice on TRAILING_MOVE", () => {
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE", detail: { newStopPrice: 1.2345 } }).success).toBe(true);
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE" }).success).toBe(false);
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE", detail: {} }).success).toBe(false);
  });

  it("REQUIRES levelId + executedPrice + closedVolume on PARTIAL_TP", () => {
    expect(schema.safeParse({ ...base, action: "PARTIAL_TP", detail: { levelId: "tp-1", executedPrice: 1, closedVolume: 0.5 } }).success).toBe(true);
    expect(schema.safeParse({ ...base, action: "PARTIAL_TP", detail: { levelId: "tp-1", executedPrice: 1 } }).success).toBe(false);
    expect(schema.safeParse({ ...base, action: "PARTIAL_TP", detail: { levelId: "tp-1", closedVolume: 0.5 } }).success).toBe(false);
  });

  it("rejects unknown action spelling", () => {
    expect(schema.safeParse({ ...base, action: "PARTIAL_CLOSE", detail: {} }).success).toBe(false);
    expect(schema.safeParse({ ...base, action: "BREAKEVEN" }).success).toBe(false);
  });
});

describe("action_failed payload schema", () => {
  const schema = actionFailedPayloadSchema();
  const base = { positionId: "pos-1", planId: "plan-1" };

  it("accepts a valid failure with reason + retryable", () => {
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE", reason: "broker rejected", retryable: true }).success).toBe(true);
  });

  it("rejects a failure missing reason or retryable", () => {
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE", retryable: true }).success).toBe(false);
    expect(schema.safeParse({ ...base, action: "TRAILING_MOVE", reason: "x" }).success).toBe(false);
  });

  it("accepts optional levelId (PARTIAL_TP)", () => {
    expect(schema.safeParse({ ...base, action: "PARTIAL_TP", reason: "no liquidity", retryable: false, levelId: "tp-1" }).success).toBe(true);
  });
});
