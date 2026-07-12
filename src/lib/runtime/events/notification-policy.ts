// Notification policy — decides whether an event becomes a toast, a persistent
// entry in the notification center, or is silently recorded.

import type { RuntimeEventEnvelope, RuntimeEventType } from "./event-types";
import { SEVERITY_ORDER } from "./event-types";

export interface EventNotificationDecision {
  showToast: boolean;
  createAlert: boolean;
  createIncidentCandidate: boolean;
  playSound: boolean;
  persistInNotificationCenter: boolean;
  dedupeKey?: string;
  cooldownMs?: number;
  priority: "LOW" | "NORMAL" | "HIGH" | "CRITICAL";
}

/** Critical types that must always create persistent notifications. */
const CRITICAL_TYPES = new Set<RuntimeEventType>([
  "command.execution_unknown",
  "order.execution_unknown",
  "position.execution_unknown",
  "position.unprotected",
  "safety.circuit_breaker.opened",
  "safety.kill.failed",
  "runtime.safe_mode.changed",
  "reconciliation.failed",
  "system.event_gap.detected",
]);

/** Silent types — recorded but never toasted. */
const SILENT_TYPES = new Set<RuntimeEventType>([
  "command.created",
  "command.progress",
  "broker.request.completed",
  "strategy.signal.generated",
  "risk.evaluation.completed",
]);

const INFO_TYPES = new Set<RuntimeEventType>([
  "runtime.state.changed",
  "runtime.connection.changed",
  "configuration.applied",
  "safety.entries.enabled",
  "reconciliation.completed",
  "alert.acknowledged",
]);

export function decideNotification(env: RuntimeEventEnvelope): EventNotificationDecision {
  const critical =
    CRITICAL_TYPES.has(env.type) || env.severity === "CRITICAL";
  if (critical) {
    return {
      showToast: true,
      createAlert: true,
      createIncidentCandidate: true,
      playSound: false,
      persistInNotificationCenter: true,
      dedupeKey: dedupeKey(env),
      cooldownMs: 2000,
      priority: "CRITICAL",
    };
  }

  if (SILENT_TYPES.has(env.type) && SEVERITY_ORDER[env.severity] < SEVERITY_ORDER.WARNING) {
    return {
      showToast: false,
      createAlert: false,
      createIncidentCandidate: false,
      playSound: false,
      persistInNotificationCenter: false,
      priority: "LOW",
    };
  }

  if (env.severity === "ERROR" || env.severity === "WARNING") {
    return {
      showToast: true,
      createAlert: env.severity === "ERROR",
      createIncidentCandidate: env.severity === "ERROR",
      playSound: false,
      persistInNotificationCenter: true,
      dedupeKey: dedupeKey(env),
      cooldownMs: env.severity === "ERROR" ? 5000 : 8000,
      priority: env.severity === "ERROR" ? "HIGH" : "NORMAL",
    };
  }

  if (INFO_TYPES.has(env.type)) {
    return {
      showToast: true,
      createAlert: false,
      createIncidentCandidate: false,
      playSound: false,
      persistInNotificationCenter: true,
      dedupeKey: dedupeKey(env),
      cooldownMs: 10000,
      priority: "NORMAL",
    };
  }

  return {
    showToast: false,
    createAlert: false,
    createIncidentCandidate: false,
    playSound: false,
    persistInNotificationCenter: SEVERITY_ORDER[env.severity] >= SEVERITY_ORDER.INFO,
    priority: "LOW",
  };
}

function dedupeKey(env: RuntimeEventEnvelope): string {
  const entity =
    env.orderId ??
    env.positionId ??
    env.strategyId ??
    env.incidentId ??
    env.commandId ??
    env.correlationId ??
    "-";
  return `${env.type}|${env.severity}|${entity}`;
}
