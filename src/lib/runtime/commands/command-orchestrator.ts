// Phase 5D — Command Submission Orchestrator.
// Single entry point for every trading/runtime command. Pages MUST call
// `submitCommand()` from here (directly, or via <CommandButton />) and MUST NOT
// call the adapter directly.
//
// Responsibilities: capability resolution, connection/safe-mode gating,
// freshness gating, reconciliation gating, execution-unknown lock gating,
// operator role gating, active-command dedupe, deterministic idempotency,
// adapter submission, and result reporting. No auto-retry for trading commands.

import { getRuntimeAdapter } from "../index";
import { commandStore, isTerminal, makeRequest } from "../runtime-command-store";
import { evaluateHandshake } from "../runtime-handshake";
import { classifyFreshness, commandsBlockedByRestriction, restrictionFor } from "../state/freshness-policy";
import { deriveIdempotencyKey } from "./command-equivalence";
import { executionUnknownLocks } from "../state/execution-unknown-lock";
import { evaluateReconciliation, isCommandBlockedByReconciliation } from "../state/reconciliation-restrictions";
import { roleAllows, roleBlockReason } from "../state/operator-role";
import type { RuntimeCommandKind } from "../runtime-types";

export interface CommandSubmissionInput {
  kind: RuntimeCommandKind;
  targetId?: string;
  reason?: string;
  parameters?: Record<string, unknown>;
  expectedRevision?: number;
  /**
   * Optional caller-supplied idempotency override. Almost never needed — the
   * orchestrator derives a deterministic equivalence key by default.
   */
  idempotencyKey?: string;
}

export type SubmissionBlockCode =
  | "CAPABILITY_DENIED"
  | "ROLE_DENIED"
  | "SAFE_MODE"
  | "DISCONNECTED"
  | "STALE_DATA"
  | "RECONCILIATION_BLOCK"
  | "EXECUTION_UNKNOWN_LOCK"
  | "ADAPTER_ERROR";

export interface CommandSubmissionResult {
  accepted: boolean;
  commandId?: string;
  existingCommandId?: string;
  deduplicated?: boolean;
  blockedCode?: SubmissionBlockCode;
  blockedReason?: string;
}

/**
 * Evaluate whether a command would be accepted right now, WITHOUT submitting.
 * Used by <CommandButton /> for pre-confirmation and pre-submission
 * revalidation.
 */
export function evaluateSubmission(input: CommandSubmissionInput): CommandSubmissionResult {
  const adapter = getRuntimeAdapter();

  // 1. Connection
  const conn = adapter.getConnectionState();
  if (conn.state === "DISCONNECTED" || conn.state === "ERROR") {
    return {
      accepted: false,
      blockedCode: "DISCONNECTED",
      blockedReason: "Runtime is not connected — command cannot be submitted.",
    };
  }

  // 2. Safe mode (handshake incompatible)
  const compat = evaluateHandshake(adapter.getHandshake());
  if (compat.safeMode) {
    return {
      accepted: false,
      blockedCode: "SAFE_MODE",
      blockedReason: "SAFE MODE — runtime schema/protocol incompatible with frontend.",
    };
  }

  // 3. Capability
  const capability = adapter.getCapabilities().commands[input.kind];
  if (!capability || !capability.allowed) {
    return {
      accepted: false,
      blockedCode: "CAPABILITY_DENIED",
      blockedReason: capability?.reason ?? "Command not permitted in the current runtime state.",
    };
  }

  // 4. Operator role
  const operator = adapter.getOperator();
  if (!roleAllows(operator.role, input.kind)) {
    return {
      accepted: false,
      blockedCode: "ROLE_DENIED",
      blockedReason: roleBlockReason(operator.role, input.kind),
    };
  }

  // 5. Freshness (broker/market/runtime staleness → trading blocks)
  const brokerAgeMs = conn.dataAgeMs ?? 0;
  const brokerLevel = classifyFreshness("broker", brokerAgeMs);
  const brokerRestriction = restrictionFor("broker", brokerLevel);
  const blockedByBroker = commandsBlockedByRestriction(brokerRestriction).includes(input.kind);
  if (blockedByBroker) {
    return {
      accepted: false,
      blockedCode: "STALE_DATA",
      blockedReason: `Broker data ${brokerLevel} — trading commands are temporarily blocked.`,
    };
  }

  // 6. Reconciliation restrictions
  const rec = evaluateReconciliation(adapter.getSnapshot().reconciliation);
  if (isCommandBlockedByReconciliation(rec, input.kind, input.targetId)) {
    return {
      accepted: false,
      blockedCode: "RECONCILIATION_BLOCK",
      blockedReason: rec.reason,
    };
  }

  // 7. Execution-unknown lock
  const lock = executionUnknownLocks.isBlocked(input.kind, input.targetId);
  if (lock) {
    return {
      accepted: false,
      blockedCode: "EXECUTION_UNKNOWN_LOCK",
      blockedReason:
        "A prior command on this entity resulted in EXECUTION_UNKNOWN. Retry blocked until reconciliation resolves broker state.",
    };
  }

  // 8. Active equivalent command → return existing.
  const idKey =
    input.idempotencyKey ?? deriveIdempotencyKey(input.kind, input.targetId, input.parameters);
  const active = commandStore.findActiveByIdempotency(idKey);
  if (active) {
    return {
      accepted: true,
      deduplicated: true,
      commandId: active.commandId,
      existingCommandId: active.commandId,
    };
  }

  return { accepted: true };
}

/**
 * Submit a command through the orchestrator. Performs all gating in
 * evaluateSubmission first, then hands to the adapter. Trading commands are
 * never auto-retried on failure — that is a deliberate operator action.
 */
export async function submitCommand(input: CommandSubmissionInput): Promise<CommandSubmissionResult> {
  const pre = evaluateSubmission(input);
  if (!pre.accepted || pre.deduplicated) return pre;

  const idempotencyKey =
    input.idempotencyKey ?? deriveIdempotencyKey(input.kind, input.targetId, input.parameters);

  const request = makeRequest(input.kind, {
    targetId: input.targetId,
    reason: input.reason,
    parameters: input.parameters,
    expectedRevision: input.expectedRevision,
    idempotencyKey,
  });

  try {
    const accepted = await getRuntimeAdapter().submitCommand(request);
    return { accepted: true, commandId: accepted.commandId };
  } catch (err) {
    return {
      accepted: false,
      blockedCode: "ADAPTER_ERROR",
      blockedReason: err instanceof Error ? err.message : String(err),
    };
  }
}

/**
 * Called by adapters/event router whenever a command reaches
 * EXECUTION_UNKNOWN — acquires the corresponding entity lock.
 */
export function registerExecutionUnknown(status: {
  commandId: string;
  kind: RuntimeCommandKind;
  targetId?: string;
  correlationId?: string;
}) {
  executionUnknownLocks.acquire({
    commandId: status.commandId,
    kind: status.kind,
    targetId: status.targetId,
    correlationId: status.correlationId,
    operation:
      status.kind.startsWith("position.close")
        ? "CLOSE"
        : status.kind === "order.cancel" || status.kind === "order.cancelAll"
          ? "CANCEL"
          : status.kind === "position.modifyProtection"
            ? "PROTECTION"
            : status.kind === "runtime.emergencyKill"
              ? "KILL_STEP"
              : status.kind.startsWith("order.")
                ? "SUBMIT"
                : "OTHER",
  });
}

export { isTerminal };
