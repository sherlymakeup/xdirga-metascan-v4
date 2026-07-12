import { describe, it, expect } from "vitest";
import { decideNotification } from "../events/notification-policy";
import type { RuntimeEventEnvelope } from "../events/runtime-event-envelope";

function env(
  overrides: Partial<RuntimeEventEnvelope> & { type: RuntimeEventEnvelope["type"] },
): RuntimeEventEnvelope {
  return {
    eventId: "e",
    runtimeId: "rt",
    bootId: "b",
    revision: 1,
    sequence: 1,
    occurredAt: "",
    emittedAt: "",
    receivedAt: "",
    severity: "INFO",
    source: "DEVELOPMENT_FIXTURE",
    payload: {},
    ...overrides,
  };
}

describe("notification-policy", () => {
  it("execution-unknown always escalates to CRITICAL", () => {
    const d = decideNotification(env({ type: "position.execution_unknown", severity: "WARNING" }));
    expect(d.priority).toBe("CRITICAL");
    expect(d.persistInNotificationCenter).toBe(true);
    expect(d.createIncidentCandidate).toBe(true);
  });

  it("routine command.progress is silent", () => {
    const d = decideNotification(env({ type: "command.progress", severity: "INFO" }));
    expect(d.showToast).toBe(false);
    expect(d.persistInNotificationCenter).toBe(false);
  });

  it("ERROR severity toasts and creates an alert", () => {
    const d = decideNotification(env({ type: "broker.request.failed", severity: "ERROR" }));
    expect(d.showToast).toBe(true);
    expect(d.createAlert).toBe(true);
    expect(d.priority).toBe("HIGH");
  });

  it("gap detection is CRITICAL regardless of severity", () => {
    const d = decideNotification(env({ type: "system.event_gap.detected", severity: "INFO" }));
    expect(d.priority).toBe("CRITICAL");
  });
});
