// Phase 5D — reconciliation-derived command restrictions (centralized selector).

import { useMemo } from "react";
import { useSnapshot } from "../index";
import type { RuntimeCommandKind } from "../runtime-types";
import type { ReconciliationSummary } from "@/lib/types";

export interface ReconciliationRestriction {
  blocked: boolean;
  reason?: string;
  affectedCommands: RuntimeCommandKind[];
  affectedEntityIds: string[];
}

export function evaluateReconciliation(
  summary: ReconciliationSummary | undefined | null,
): ReconciliationRestriction {
  if (!summary) {
    return { blocked: false, affectedCommands: [], affectedEntityIds: [] };
  }
  const unresolved = summary.issues.filter((i) => !i.resolved);
  if (summary.state === "FAILED") {
    return {
      blocked: true,
      reason: "Reconciliation failed — new entries disabled until it completes cleanly.",
      affectedCommands: [
        "runtime.enableEntries",
        "runtime.resume",
        "runtime.start",
        "strategy.resume",
        "config.apply",
      ],
      affectedEntityIds: unresolved.map((i) => i.entityId),
    };
  }
  if (unresolved.length === 0) {
    return { blocked: false, affectedCommands: [], affectedEntityIds: [] };
  }

  const affectedCommands = new Set<RuntimeCommandKind>();
  const affectedEntityIds: string[] = [];
  for (const issue of unresolved) {
    affectedEntityIds.push(issue.entityId);
    if (issue.entity === "POSITION") {
      affectedCommands.add("position.close");
      affectedCommands.add("position.closePartial");
      affectedCommands.add("position.modifyProtection");
    } else if (issue.entity === "ORDER") {
      affectedCommands.add("order.cancel");
    }
  }
  return {
    blocked: true,
    reason: `Reconciliation has ${unresolved.length} unresolved issue(s). Retries blocked on affected entities.`,
    affectedCommands: Array.from(affectedCommands),
    affectedEntityIds,
  };
}

export function useReconciliationRestriction(): ReconciliationRestriction {
  const snapshot = useSnapshot();
  return useMemo(() => evaluateReconciliation(snapshot.reconciliation), [snapshot.reconciliation]);
}

/** True when a specific command against a specific target is blocked by reconciliation. */
export function isCommandBlockedByReconciliation(
  restriction: ReconciliationRestriction,
  kind: RuntimeCommandKind,
  targetId?: string,
): boolean {
  if (!restriction.blocked) return false;
  if (!restriction.affectedCommands.includes(kind)) return false;
  if (!targetId) return true; // global restrictions
  return restriction.affectedEntityIds.includes(targetId);
}
