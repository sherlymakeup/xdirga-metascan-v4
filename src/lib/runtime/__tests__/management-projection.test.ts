// Phase 5F.5 — position.management.* projection reducer lifecycle.
// Exercises the pure `applyManagementEvent` reducer end-to-end:
// plan_changed -> BE applied -> 2 trailing moves -> partial TP #1 executed.

import { describe, it, expect } from "vitest";
import { applyManagementEvent, type PositionManagementProjection } from "../domain/projections";
import type { RuntimeEventEnvelope } from "../runtime-types";

const positionId = "pos-1";
const planId = "plan-lifecycle-1";

function env(
  type: string,
  payload: Record<string, unknown>,
  sequence: number,
): RuntimeEventEnvelope {
  const now = new Date(1_700_000_000_000 + sequence * 1000).toISOString();
  return {
    eventId: `e-${sequence}`,
    type: type as RuntimeEventEnvelope["type"],
    runtimeId: "rt",
    bootId: "boot-1",
    revision: sequence,
    sequence,
    occurredAt: now,
    emittedAt: now,
    receivedAt: now,
    severity: "INFO",
    source: "DEVELOPMENT_FIXTURE",
    positionId,
    payload,
  };
}

const seedPlan = {
  planId,
  source: "STRATEGY" as const,
  breakEven: { enabled: true, triggerR: 1, offsetPoints: 2, state: "PENDING" as const, appliedAt: null },
  trailing: { mode: "STEP" as const, active: false, distancePoints: 100, currentStopPrice: null, lastMovedAt: null, moveCount: 0 },
  partialTp: { levels: [
    { levelId: "tp-1", atR: 1, closePercent: 50, state: "PENDING" as const, executedAt: null, executedPrice: null, closedVolume: null },
    { levelId: "tp-2", atR: 2, closePercent: 30, state: "PENDING" as const, executedAt: null, executedPrice: null, closedVolume: null },
  ]},
  timeExit: { maxHoldUntil: null, state: "PENDING" as const },
  nextAction: null,
  lastError: null,
  paused: false,
};

describe("management projection lifecycle", () => {
  it("plan_changed installs the plan", () => {
    const next = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1));
    expect(next?.planId).toBe(planId);
    expect(next?.breakEven.state).toBe("PENDING");
    expect(next?.trailing.moveCount).toBe(0);
  });

  it("BE action_executed flips breakEven.state to APPLIED", () => {
    let s = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1))!;
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "BREAK_EVEN", detail: {} }, 2))!;
    expect(s.breakEven.state).toBe("APPLIED");
    expect(s.breakEven.appliedAt).not.toBeNull();
    expect(s.lastError).toBeNull();
  });

  it("two TRAILING_MOVE events increment moveCount and update stop", () => {
    let s: PositionManagementProjection | undefined = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: 1.0862 } }, 2));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: 1.0874 } }, 3));
    expect(s?.trailing.active).toBe(true);
    expect(s?.trailing.moveCount).toBe(2);
    expect(s?.trailing.currentStopPrice).toBe(1.0874);
  });

  it("PARTIAL_TP marks the named level EXECUTED and leaves others PENDING", () => {
    let s: PositionManagementProjection | undefined = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "PARTIAL_TP", detail: { levelId: "tp-1", executedPrice: 1.088, closedVolume: 0.5 } }, 2));
    const l1 = s!.partialTp.levels.find((l) => l.levelId === "tp-1")!;
    const l2 = s!.partialTp.levels.find((l) => l.levelId === "tp-2")!;
    expect(l1.state).toBe("EXECUTED");
    expect(l1.executedPrice).toBe(1.088);
    expect(l1.closedVolume).toBe(0.5);
    expect(l2.state).toBe("PENDING");
  });

  it("action_failed records lastError and marks PARTIAL_TP level FAILED", () => {
    let s: PositionManagementProjection | undefined = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1));
    s = applyManagementEvent(s, env("position.management.action_failed", { positionId, planId, action: "PARTIAL_TP", reason: "no liquidity", retryable: false, levelId: "tp-1" }, 2));
    expect(s?.lastError).toBe("no liquidity");
    expect(s?.partialTp.levels.find((l) => l.levelId === "tp-1")?.state).toBe("FAILED");
  });

  it("full lifecycle produces the expected end-state", () => {
    let s: PositionManagementProjection | undefined = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "BREAK_EVEN", detail: {} }, 2));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: 1.0862 } }, 3));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "TRAILING_MOVE", detail: { newStopPrice: 1.0874 } }, 4));
    s = applyManagementEvent(s, env("position.management.action_executed", { positionId, planId, action: "PARTIAL_TP", detail: { levelId: "tp-1", executedPrice: 1.088, closedVolume: 0.5 } }, 5));
    expect(s?.breakEven.state).toBe("APPLIED");
    expect(s?.trailing.moveCount).toBe(2);
    expect(s?.trailing.currentStopPrice).toBe(1.0874);
    expect(s?.partialTp.levels.find((l) => l.levelId === "tp-1")?.state).toBe("EXECUTED");
    expect(s?.partialTp.levels.find((l) => l.levelId === "tp-2")?.state).toBe("PENDING");
    expect(s?.lastError).toBeNull();
  });

  it("ignores non-management envelopes", () => {
    const start = applyManagementEvent(undefined, env("position.management.plan_changed", { positionId, plan: seedPlan }, 1))!;
    const unchanged = applyManagementEvent(start, env("position.opened", { positionId }, 2));
    expect(unchanged).toBe(start);
  });
});
