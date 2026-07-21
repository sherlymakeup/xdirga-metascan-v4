// Public entry point for the runtime layer.
// Selects the active adapter from the explicit build-time source, exposes hooks + command helpers.

import { useSyncExternalStore, useMemo } from "react";
import type { CockpitSnapshot, ScenarioKey } from "@/lib/types";
import { MockRuntimeAdapter } from "./mock-runtime-adapter";
import { HttpRuntimeAdapter } from "./http-runtime-adapter";
import type { RuntimeAdapter } from "./runtime-adapter";
import { commandStore, isTerminal, makeRequest } from "./runtime-command-store";
import { evaluateHandshake } from "./runtime-handshake";
import type {
  CommandCapability,
  HandshakeCompatibility,
  RuntimeCapabilities,
  RuntimeCommandKind,
  RuntimeCommandRequest,
  RuntimeCommandStatus,
  RuntimeConnectionStateSnapshot,
  RuntimeHandshake,
} from "./runtime-types";

// -----------------------------------------------------------------------------
// Adapter singleton — data source resolved at module init.
//
// "fixture" = DEVELOPMENT_FIXTURE frontend data source (no runtime, no broker).
// "http"    = LOCAL_RUNTIME via HTTP/SSE (XDirga Runtime V4) — not yet wired.
//
// These are FRONTEND DATA SOURCES, not trading modes. There is intentionally
// no operator-facing selector for DEMO / PAPER / REPLAY.
// -----------------------------------------------------------------------------

export type RuntimeDataSource = "fixture" | "http";
/** @deprecated use RuntimeDataSource; retained for compat with early phases. */
export type RuntimeMode = RuntimeDataSource;

function resolveInitialMode(): RuntimeDataSource {
  const envMode = (import.meta.env?.VITE_RUNTIME_MODE as string | undefined)?.toLowerCase();
  return envMode === "fixture" && import.meta.env?.DEV ? "fixture" : "http";
}

function buildAdapter(mode: RuntimeDataSource): RuntimeAdapter {
  if (mode === "http") {
    const baseUrl = (import.meta.env?.VITE_RUNTIME_BASE_URL as string | undefined) ?? "";
    const authToken = (import.meta.env?.VITE_RUNTIME_TOKEN as string | undefined) ?? "";
    return new HttpRuntimeAdapter({ baseUrl, authToken });
  }
  return new MockRuntimeAdapter();
}

const runtimeMode: RuntimeDataSource = resolveInitialMode();
const adapter: RuntimeAdapter = buildAdapter(runtimeMode);
void adapter.connect().catch(() => {
  /* connection errors surface via getConnectionState */
});

export function getRuntimeAdapter(): RuntimeAdapter {
  return adapter;
}

export function getRuntimeMode(): RuntimeDataSource {
  return runtimeMode;
}
export const getRuntimeDataSource = getRuntimeMode;

/** Runtime source is build-time only; production cannot be switched to fixtures. */
export function setRuntimeMode(_mode: RuntimeDataSource): void {
  void _mode;
}
export const setRuntimeDataSource = setRuntimeMode;

export function hydrateScenarioFromStorage() {}

// -----------------------------------------------------------------------------
// Hooks
// -----------------------------------------------------------------------------

export function useSnapshot(): CockpitSnapshot {
  return useSyncExternalStore(
    (l) => adapter.subscribeSnapshot(() => l()),
    () => adapter.getSnapshot(),
    () => adapter.getSnapshot(),
  );
}

export function useConnectionState(): RuntimeConnectionStateSnapshot {
  return useSyncExternalStore(
    (l) => adapter.subscribeConnection(() => l()),
    () => adapter.getConnectionState(),
    () => adapter.getConnectionState(),
  );
}

export function useHasValidatedSnapshot(): boolean {
  return useSyncExternalStore(
    (l) => adapter.subscribeSnapshot(() => l()),
    () => getHasValidatedSnapshot(adapter),
    () => getHasValidatedSnapshot(adapter),
  );
}

function getHasValidatedSnapshot(a: RuntimeAdapter): boolean {
  if ("hasValidatedSnapshotPublished" in a && typeof a.hasValidatedSnapshotPublished === "function") {
    return a.hasValidatedSnapshotPublished();
  }
  return true;
}

export function useCapabilities(): RuntimeCapabilities {
  // Capabilities are recomputed on scenario change; snapshot subscription is a good trigger.
  return useSyncExternalStore(
    (l) => adapter.subscribeSnapshot(() => l()),
    () => adapter.getCapabilities(),
    () => adapter.getCapabilities(),
  );
}

export function useHandshake(): RuntimeHandshake | null {
  return useSyncExternalStore(
    (l) => adapter.subscribeHandshake(() => l()),
    () => adapter.getHandshake(),
    () => adapter.getHandshake(),
  );
}

export function useHandshakeCompatibility(): HandshakeCompatibility {
  const handshake = useHandshake();
  return useMemo(() => evaluateHandshake(handshake), [handshake]);
}

/**
 * Capability lookup with SAFE MODE enforcement. If the runtime handshake is
 * incompatible with the frontend, every command is forced to `allowed: false`
 * with an explanatory reason. The runtime-reported capability is preserved on
 * `.riskLevel` / `.confirmationPhrase` for context.
 */
export function useCapability(kind: RuntimeCommandKind): CommandCapability | undefined {
  const base = useCapabilities().commands[kind];
  const compat = useHandshakeCompatibility();
  return useMemo(() => {
    if (!base) return base;
    if (!compat.safeMode) return base;
    return {
      ...base,
      allowed: false,
      reason: "SAFE MODE — runtime schema/protocol incompatible with frontend.",
    };
  }, [base, compat.safeMode]);
}

export function useScenario(): ScenarioKey {
  return useSyncExternalStore(
    (l) => adapter.subscribeSnapshot(() => l()),
    () => (adapter.getScenario ? adapter.getScenario() : ("healthy" as ScenarioKey)),
    () => (adapter.getScenario ? adapter.getScenario() : ("healthy" as ScenarioKey)),
  );
}

/** Subscribe to the command store as a whole. */
export function useCommandStore(): RuntimeCommandStatus[] {
  return useSyncExternalStore(
    (l) => commandStore.subscribe(l),
    () => commandStore.list(),
    () => commandStore.list(),
  );
}

export function useCommandCounts() {
  return useSyncExternalStore(
    (l) => commandStore.subscribe(l),
    () => commandStore.counts(),
    () => commandStore.counts(),
  );
}

export function useCommand(commandId: string | null | undefined): RuntimeCommandStatus | undefined {
  return useSyncExternalStore(
    (l) => commandStore.subscribe(l),
    () => (commandId ? commandStore.get(commandId) : undefined),
    () => (commandId ? commandStore.get(commandId) : undefined),
  );
}

// -----------------------------------------------------------------------------
// Command helpers
// -----------------------------------------------------------------------------

/**
 * Submit a command through the central orchestrator. All safety gating
 * (connection, safe mode, capability, role, freshness, reconciliation,
 * EXECUTION_UNKNOWN locks, idempotency dedup) runs inside
 * `commandOrchestrator.submitCommand`. Blocked results throw so legacy
 * callers surface the error — new code should call `submitCommand` from
 * `@/lib/runtime` (orchestrator) directly and inspect the structured result.
 */
export async function submitRuntimeCommand(
  kind: RuntimeCommandKind,
  opts: {
    targetId?: string;
    reason?: string;
    parameters?: Record<string, unknown>;
    expectedRevision?: number;
    idempotencyKey?: string;
  } = {},
): Promise<{ commandId: string; deduplicated: boolean }> {
  const { submitCommand: orchestrate } = await import("./commands/command-orchestrator");
  const result = await orchestrate({ kind, ...opts });
  if (!result.accepted) {
    throw new Error(
      result.blockedReason ?? `Command blocked (${result.blockedCode ?? "UNKNOWN"}).`,
    );
  }
  return {
    commandId: result.commandId ?? result.existingCommandId ?? "",
    deduplicated: Boolean(result.deduplicated),
  };
}

/** Wait for a command to reach a terminal state. Resolves with the final status. */
export function awaitCommandTerminal(
  commandId: string,
  timeoutMs = 15000,
): Promise<RuntimeCommandStatus> {
  return new Promise((resolve, reject) => {
    const existing = commandStore.get(commandId);
    if (existing && isTerminal(existing.state)) {
      resolve(existing);
      return;
    }
    const unsubscribe = commandStore.subscribe(() => {
      const s = commandStore.get(commandId);
      if (s && isTerminal(s.state)) {
        unsubscribe();
        clearTimeout(timer);
        resolve(s);
      }
    });
    const timer = setTimeout(() => {
      unsubscribe();
      const s = commandStore.get(commandId);
      if (s) resolve(s);
      else reject(new Error(`Timed out waiting for command ${commandId}`));
    }, timeoutMs);
  });
}

export { commandStore, isTerminal, makeRequest };
export type { RuntimeAdapter };
export * from "./runtime-types";

// Phase 5D — state primitives + command orchestrator.
export {
  classifyFreshness,
  restrictionFor,
  commandsBlockedByRestriction,
} from "./state/freshness-policy";
export { executionUnknownLocks, useExecutionUnknownLocks } from "./state/execution-unknown-lock";
export {
  useReconciliationRestriction,
  evaluateReconciliation,
  isCommandBlockedByReconciliation,
} from "./state/reconciliation-restrictions";
export { roleAllows, roleBlockReason } from "./state/operator-role";
export {
  useGlobalOperationalState,
  type GlobalOperationalState,
  type GlobalOperationalStateKind,
} from "./state/operational-state";
export { useApplicationHydration, type ApplicationHydrationState } from "./state/hydration";
export {
  snapshotHydrationStore,
  useSnapshotHydration,
  type SnapshotAcceptanceReason,
  type SnapshotHydrationState,
} from "./state/snapshot-hydration";
export {
  submitCommand,
  evaluateSubmission,
  type CommandSubmissionInput,
  type CommandSubmissionResult,
  type SubmissionBlockCode,
} from "./commands/command-orchestrator";
export { deriveIdempotencyKey } from "./commands/command-equivalence";

// Phase 5E.2 — domain projections derived from the event stream.
export {
  bootstrapDomainProjections,
  useOrderProjections,
  usePositionProjections,
  useIncidentProjections,
  useReconciliationRunProjections,
  orderProjectionStore,
  positionProjectionStore,
  incidentProjectionStore,
  reconciliationRunProjectionStore,
  type OrderProjection,
  type PositionProjection,
  type IncidentProjection,
  type ReconciliationRunProjection,
} from "./domain/projections";

// Phase 5F.2 — snapshot ↔ event stream convergence.
export {
  convergenceStore,
  useConvergence,
  type ConvergenceState,
  type ConvergenceStatus,
} from "./state/convergence";
