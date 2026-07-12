// COMPAT SHIM — the runtime adapter has moved to `@/lib/runtime`.
// This file preserves the old import surface for existing pages during migration.
// New code should import from `@/lib/runtime` directly.

import {
  awaitCommandTerminal,
  getRuntimeAdapter as getAdapterNew,
  hydrateScenarioFromStorage as hydrateNew,
  submitRuntimeCommand,
  useScenario as useScenarioNew,
  useSnapshot as useSnapshotNew,
} from "@/lib/runtime";
import type { RuntimeCommandKind } from "@/lib/runtime";

export { useSnapshotNew as useSnapshot, useScenarioNew as useScenario };
export const hydrateScenarioFromStorage = hydrateNew;

// ---- Legacy command surface ------------------------------------------------
// The old `RuntimeCommand` union is preserved so existing pages compile without edits.

export type RuntimeCommand =
  | { kind: "runtime.start" }
  | { kind: "runtime.pause" }
  | { kind: "runtime.resume" }
  | { kind: "runtime.stop" }
  | { kind: "runtime.restart" }
  | { kind: "runtime.reconnectBroker" }
  | { kind: "runtime.reconcile" }
  | { kind: "runtime.emergencyKill"; reason: string; steps: string[] }
  | { kind: "runtime.disableEntries" }
  | { kind: "runtime.enableEntries" }
  | { kind: "position.close"; positionId: string; reason: string }
  | { kind: "position.closeAll"; reason: string }
  | { kind: "order.cancel"; orderId: string; reason: string }
  | { kind: "order.cancelAll"; reason: string }
  | { kind: "breaker.reset"; key: string; reason: string }
  | { kind: "alert.acknowledge"; id: string };

export interface CommandResult {
  status: "COMMAND_PREPARED" | "COMMAND_SENT" | "RUNTIME_ACK" | "COMPLETED" | "FAILED" | "TIMED_OUT" | "UNKNOWN";
  message: string;
  correlationId: string;
}

/**
 * Legacy compatibility wrapper. Routes commands through the new command store
 * and waits for a terminal state. The `status` reflects the real lifecycle
 * outcome — no more optimistic "COMPLETED" on Promise resolve.
 */
async function sendCommand(command: RuntimeCommand): Promise<CommandResult> {
  const { kind } = command;
  const anyCmd = command as Record<string, unknown>;
  const { commandId } = await submitRuntimeCommand(kind as RuntimeCommandKind, {
    targetId: (anyCmd.positionId ?? anyCmd.orderId ?? anyCmd.id ?? anyCmd.key) as string | undefined,
    reason: anyCmd.reason as string | undefined,
    parameters: anyCmd.steps ? { steps: anyCmd.steps } : undefined,
  });
  const final = await awaitCommandTerminal(commandId);
  const map: Record<string, CommandResult["status"]> = {
    COMPLETED: "COMPLETED",
    FAILED: "FAILED",
    TIMED_OUT: "TIMED_OUT",
    EXECUTION_UNKNOWN: "UNKNOWN",
    CANCELLED: "FAILED",
  };
  return {
    status: map[final.state] ?? "COMPLETED",
    message: final.message ?? final.errorMessage ?? `Runtime state: ${final.state}`,
    correlationId: final.correlationId,
  };
}

/** Legacy adapter shape returned by `getRuntimeAdapter()`. */
export interface RuntimeAdapter {
  getSnapshot: ReturnType<typeof getAdapterNew>["getSnapshot"];
  subscribe: (listener: () => void) => () => void;
  setScenario: NonNullable<ReturnType<typeof getAdapterNew>["setScenario"]>;
  getScenario: NonNullable<ReturnType<typeof getAdapterNew>["getScenario"]>;
  isDemo: ReturnType<typeof getAdapterNew>["isDemo"];
  sendCommand: (command: RuntimeCommand) => Promise<CommandResult>;
}

export function getRuntimeAdapter(): RuntimeAdapter {
  const a = getAdapterNew();
  return {
    getSnapshot: a.getSnapshot.bind(a),
    subscribe: (listener: () => void) => a.subscribeSnapshot(() => listener()),
    setScenario: (s) => a.setScenario!(s),
    getScenario: () => a.getScenario!(),
    isDemo: a.isDemo.bind(a),
    sendCommand,
  };
}
