// Phase 5D — centralized operator role model. Presentation only; the backend
// remains the security authority. Fixture identities are development-only.

import { useMemo } from "react";
import { useSyncExternalStore } from "react";
import { getRuntimeAdapter } from "../index";
import type { OperatorRole, RuntimeCommandKind } from "../runtime-types";

const OPERATOR_ALLOWED: RuntimeCommandKind[] = [
  "runtime.pause",
  "runtime.resume",
  "runtime.reconnectBroker",
  "runtime.reconcile",
  "runtime.disableEntries",
  "runtime.enableEntries",
  "order.cancel",
  "order.cancelAll",
  "position.close",
  "position.closePartial",
  "position.closeAll",
  "position.modifyProtection",
  "strategy.pause",
  "strategy.resume",
  "alert.acknowledge",
  "incident.acknowledge",
  "position.management.pause",
  "position.management.resume",
];

const RISK_MANAGER_ONLY: RuntimeCommandKind[] = [
  "runtime.emergencyKill",
  "breaker.reset",
  "strategy.disable",
];

const ADMIN_ONLY: RuntimeCommandKind[] = [
  "runtime.start",
  "runtime.stop",
  "runtime.restart",
  "config.validate",
  "config.apply",
  "config.rollback",
];

export function roleAllows(role: OperatorRole, kind: RuntimeCommandKind): boolean {
  if (role === "VIEWER") return false;
  if (role === "ADMIN") return true;
  if (role === "RISK_MANAGER") {
    return (
      OPERATOR_ALLOWED.includes(kind) ||
      RISK_MANAGER_ONLY.includes(kind)
    );
  }
  // OPERATOR
  return OPERATOR_ALLOWED.includes(kind);
}

export function roleBlockReason(role: OperatorRole, kind: RuntimeCommandKind): string | undefined {
  if (roleAllows(role, kind)) return undefined;
  if (role === "VIEWER") return "VIEWER role has no command permissions.";
  if (role === "OPERATOR" && RISK_MANAGER_ONLY.includes(kind)) {
    return "Requires RISK_MANAGER role.";
  }
  if (ADMIN_ONLY.includes(kind)) {
    return "Requires ADMIN role.";
  }
  return `Command ${kind} is not permitted for role ${role}.`;
}

export function useOperator() {
  const adapter = getRuntimeAdapter();
  return useSyncExternalStore(
    () => () => {},
    () => adapter.getOperator(),
    () => adapter.getOperator(),
  );
}

export function useRoleCanRun(kind: RuntimeCommandKind): {
  allowed: boolean;
  reason?: string;
  role: OperatorRole;
} {
  const op = useOperator();
  return useMemo(
    () => ({ allowed: roleAllows(op.role, kind), reason: roleBlockReason(op.role, kind), role: op.role }),
    [op.role, kind],
  );
}
