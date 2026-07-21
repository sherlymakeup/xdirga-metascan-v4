// Phase 5D — command state transition table + validator.
// This is the single source of truth for command lifecycle correctness. Both
// the fixture adapter and the future HTTP/SSE adapter MUST route status
// updates through `validateTransition` — invalid transitions are dropped and
// surfaced as `system.validation.failed` events.

import type { RuntimeCommandState } from "../runtime-types";

const ALLOWED: Record<RuntimeCommandState, ReadonlyArray<RuntimeCommandState>> = {
  PREPARED: ["SUBMITTING", "CANCELLED", "FAILED"],
  SUBMITTING: ["ACCEPTED", "FAILED", "TIMED_OUT", "EXECUTION_UNKNOWN"],
  ACCEPTED: [
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED",
    "TIMED_OUT",
    "EXECUTION_UNKNOWN",
  ],
  ACKNOWLEDGED: ["IN_PROGRESS", "COMPLETED", "FAILED", "TIMED_OUT", "EXECUTION_UNKNOWN"],
  IN_PROGRESS: ["IN_PROGRESS", "COMPLETED", "FAILED", "TIMED_OUT", "EXECUTION_UNKNOWN"],
  COMPLETED: [],
  FAILED: [],
  TIMED_OUT: [],
  EXECUTION_UNKNOWN: [],
  CANCELLED: [],
} as const;

const TERMINAL = new Set<RuntimeCommandState>([
  "COMPLETED",
  "FAILED",
  "TIMED_OUT",
  "EXECUTION_UNKNOWN",
  "CANCELLED",
]);

export function isTerminalState(state: RuntimeCommandState): boolean {
  return TERMINAL.has(state);
}

export interface TransitionEvaluation {
  ok: boolean;
  reason?: string;
}

export function validateTransition(
  from: RuntimeCommandState,
  to: RuntimeCommandState,
): TransitionEvaluation {
  if (from === to) return { ok: true };
  if (TERMINAL.has(from)) {
    return { ok: false, reason: `Terminal state ${from} cannot transition to ${to}.` };
  }
  const allowed = ALLOWED[from];
  if (!allowed.includes(to)) {
    return { ok: false, reason: `Invalid transition ${from} → ${to}.` };
  }
  return { ok: true };
}
