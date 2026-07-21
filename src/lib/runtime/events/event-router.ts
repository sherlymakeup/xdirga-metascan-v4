// Event router — the single entry point for every incoming event envelope.
// Pipeline: validate → dedupe/order → history → policy → toast/notification.

import { toast } from "sonner";
import { validateEnvelope } from "./event-schemas";
import { EventDeduplicator } from "./event-deduplicator";
import { eventHistoryStore } from "./event-store";
import { decideNotification } from "./notification-policy";
import { notificationCenter } from "./notification-center";
import type { RuntimeEventEnvelope } from "./event-types";

const dedup = new EventDeduplicator();

// Toast cooldown (dedupeKey -> last emitted timestamp)
const toastCooldowns = new Map<string, number>();

export interface RouteOutcome {
  accepted: boolean;
  reason?: string;
}

/**
 * Route a raw event envelope through the pipeline. Untrusted input is
 * validated with Zod; failures never mutate authoritative state.
 */
export function routeEvent(raw: unknown): RouteOutcome {
  const validated = validateEnvelope(raw);
  if (!validated.ok || !validated.envelope) {
    // Record a synthetic system event, never crash.
    const now = new Date().toISOString();
    const systemEnv: RuntimeEventEnvelope = {
      eventId: `sys-invalid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      type: "system.validation.failed",
      runtimeId: "xdirga-runtime-frontend",
      bootId: "frontend",
      revision: 0,
      sequence: 0,
      occurredAt: now,
      emittedAt: now,
      receivedAt: now,
      severity: "ERROR",
      source: "DEVELOPMENT_FIXTURE",
      payload: { errors: validated.errors ?? ["invalid envelope"] },
    };
    eventHistoryStore.push(systemEnv);
    const decision = decideNotification(systemEnv);
    notificationCenter.ingest(systemEnv, decision);
    return { accepted: false, reason: "invalid-envelope" };
  }

  const env = validated.envelope;
  const outcome = dedup.evaluate(env);

  if (outcome.action === "drop") {
    return { accepted: false, reason: outcome.reason };
  }

  if (outcome.action === "gap") {
    const now = new Date().toISOString();
    const gapEnv: RuntimeEventEnvelope = {
      ...env,
      eventId: `sys-gap-${outcome.from}-${outcome.to}`,
      type: "system.event_gap.detected",
      severity: "WARNING",
      receivedAt: now,
      payload: { from: outcome.from, to: outcome.to, missing: outcome.missing },
    };
    eventHistoryStore.push(gapEnv);
    const decision = decideNotification(gapEnv);
    notificationCenter.ingest(gapEnv, decision);
    // Continue: the current event is also accepted (its sequence updates cursor).
  }

  if (outcome.action === "reset-boot") {
    const now = new Date().toISOString();
    const resetEnv: RuntimeEventEnvelope = {
      ...env,
      eventId: `sys-boot-${env.bootId}`,
      type: "runtime.state.changed",
      severity: "WARNING",
      receivedAt: now,
      payload: {
        note: "boot-id changed — event ordering reset",
        previousBootId: outcome.previousBootId,
      },
    };
    eventHistoryStore.push(resetEnv);
    notificationCenter.ingest(resetEnv, decideNotification(resetEnv));
  }

  eventHistoryStore.push(env);
  const decision = decideNotification(env);
  notificationCenter.ingest(env, decision);

  if (decision.showToast) {
    const key = decision.dedupeKey ?? env.eventId;
    const last = toastCooldowns.get(key) ?? 0;
    const cooldown = decision.cooldownMs ?? 3000;
    if (Date.now() - last >= cooldown) {
      toastCooldowns.set(key, Date.now());
      showToast(env, decision.priority);
    }
  }

  return { accepted: true };
}

function showToast(env: RuntimeEventEnvelope, priority: string) {
  const label = env.type;
  const message =
    typeof env.payload === "object" && env.payload && "reason" in env.payload
      ? String((env.payload as Record<string, unknown>).reason)
      : env.type.replaceAll(".", " · ");
  const fixture = env.source === "DEVELOPMENT_FIXTURE" ? " · FIXTURE" : "";
  const description = `${message}${fixture}`;
  if (priority === "CRITICAL") {
    toast.error(label, { description, duration: 8000 });
  } else if (priority === "HIGH") {
    toast.error(label, { description, duration: 6000 });
  } else if (priority === "NORMAL") {
    toast.warning(label, { description });
  } else {
    toast(label, { description });
  }
}

export function resetEventRouter() {
  dedup.reset();
  toastCooldowns.clear();
}
