// Phase 5D — Global operational state resolver. Single source of truth for
// the "how healthy is the cockpit right now" question. UI banners, cockpit
// summary, and confirmation dialogs all read from here.

import { useMemo } from "react";
import {
  useCapabilities,
  useCommandStore,
  useConnectionState,
  useHandshakeCompatibility,
  useSnapshot,
} from "../index";
import type { RuntimeCommandKind } from "../runtime-types";
import { classifyFreshness, commandsBlockedByRestriction, restrictionFor } from "./freshness-policy";
import { useExecutionUnknownLocks } from "./execution-unknown-lock";
import { useReconciliationRestriction } from "./reconciliation-restrictions";

export type GlobalOperationalStateKind =
  | "NORMAL"
  | "DEGRADED"
  | "RESTRICTED"
  | "BLOCKED"
  | "DISCONNECTED"
  | "SAFE_MODE";

export interface GlobalOperationalState {
  state: GlobalOperationalStateKind;
  reasons: string[];
  blockedCommands: RuntimeCommandKind[];
  recommendedActions: string[];
}

const SEVERITY: Record<GlobalOperationalStateKind, number> = {
  NORMAL: 0,
  DEGRADED: 1,
  RESTRICTED: 2,
  BLOCKED: 3,
  DISCONNECTED: 4,
  SAFE_MODE: 5,
};

function worse(a: GlobalOperationalStateKind, b: GlobalOperationalStateKind): GlobalOperationalStateKind {
  return SEVERITY[a] >= SEVERITY[b] ? a : b;
}

export function useGlobalOperationalState(): GlobalOperationalState {
  const snapshot = useSnapshot();
  const conn = useConnectionState();
  const compat = useHandshakeCompatibility();
  const capabilities = useCapabilities();
  const locks = useExecutionUnknownLocks();
  const reconciliation = useReconciliationRestriction();
  const commands = useCommandStore();

  return useMemo<GlobalOperationalState>(() => {
    const reasons: string[] = [];
    const blocked = new Set<RuntimeCommandKind>();
    const recommended: string[] = [];
    let state: GlobalOperationalStateKind = "NORMAL";

    if (compat.safeMode) {
      state = worse(state, "SAFE_MODE");
      reasons.push("SAFE MODE — runtime schema/protocol incompatible.");
      recommended.push("Upgrade the runtime or frontend to a compatible build.");
    }

    if (conn.state === "DISCONNECTED" || conn.state === "ERROR") {
      state = worse(state, "DISCONNECTED");
      reasons.push(`Runtime connection ${conn.state}.`);
      recommended.push("Restore local runtime connectivity.");
    } else if (conn.state === "RECONNECTING" || conn.state === "STALE") {
      state = worse(state, "DEGRADED");
      reasons.push(`Runtime connection ${conn.state}.`);
    }

    // Broker freshness
    const brokerLevel = classifyFreshness("broker", conn.dataAgeMs ?? 0);
    if (brokerLevel !== "FRESH") {
      const rest = restrictionFor("broker", brokerLevel);
      for (const c of commandsBlockedByRestriction(rest)) blocked.add(c);
      state = worse(state, rest === "TRADING_BLOCKED" ? "RESTRICTED" : "DEGRADED");
      reasons.push(`Broker data ${brokerLevel}.`);
    }

    // Runtime state
    const rs = snapshot.runtime?.state;
    if (rs === "KILLED" || rs === "STOPPED" || rs === "ERROR") {
      state = worse(state, "BLOCKED");
      reasons.push(`Runtime is ${rs}.`);
    } else if (rs === "PAUSED" || rs === "DEGRADED" || rs === "RECONCILING" || rs === "RECONNECTING") {
      state = worse(state, "DEGRADED");
      reasons.push(`Runtime is ${rs}.`);
    }

    // Reconciliation
    if (reconciliation.blocked) {
      state = worse(state, "RESTRICTED");
      if (reconciliation.reason) reasons.push(reconciliation.reason);
      for (const c of reconciliation.affectedCommands) blocked.add(c);
      recommended.push("Resolve reconciliation issues.");
    }

    // Execution-unknown locks
    if (locks.length > 0) {
      state = worse(state, "RESTRICTED");
      reasons.push(`${locks.length} execution-unknown lock(s) active.`);
      recommended.push("Run reconciliation to release execution-unknown locks.");
    }

    // Failing commands recent
    const recentFailed = commands.filter(
      (c) =>
        (c.state === "FAILED" || c.state === "TIMED_OUT") &&
        Date.now() - new Date(c.updatedAt).getTime() < 30_000,
    );
    if (recentFailed.length >= 3) {
      state = worse(state, "DEGRADED");
      reasons.push(`${recentFailed.length} recent command failures.`);
    }

    // Fold in per-command capability denials that indicate global blocks.
    for (const [kind, cap] of Object.entries(capabilities.commands)) {
      if (cap && !cap.allowed) blocked.add(kind as RuntimeCommandKind);
    }

    return {
      state,
      reasons,
      blockedCommands: Array.from(blocked),
      recommendedActions: recommended,
    };
  }, [snapshot, conn, compat.safeMode, capabilities, locks, reconciliation, commands]);
}
