import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useSyncExternalStore: (_subscribe: unknown, getSnapshot: () => unknown) => getSnapshot(),
  };
});

import { notificationCenter, useActiveEventAlerts } from "@/lib/runtime/events/notification-center";
import type { RuntimeEventEnvelope } from "@/lib/runtime/events/event-types";
import type { EventNotificationDecision } from "@/lib/runtime/events/notification-policy";

const decision: EventNotificationDecision = {
  showToast: false,
  createAlert: true,
  createIncidentCandidate: false,
  playSound: false,
  persistInNotificationCenter: true,
  priority: "HIGH",
};

function event(id: string, severity: RuntimeEventEnvelope["severity"]): RuntimeEventEnvelope {
  return {
    eventId: id,
    type: "alert.created",
    runtimeId: "runtime-1",
    bootId: "boot-1",
    revision: 1,
    sequence: 1,
    occurredAt: "2026-07-23T00:00:00Z",
    emittedAt: "2026-07-23T00:00:00Z",
    receivedAt: "2026-07-23T00:00:01Z",
    severity,
    source: "LOCAL_RUNTIME",
    payload: {
      id: `alert-${id}`,
      title: `Alert ${id}`,
      description: `Description ${id}`,
      suggestedAction: `Review ${id}`,
      ticket: 42,
      magic: 9001,
      expected: "READY",
    },
  };
}

beforeEach(() => notificationCenter.clear());

describe("useActiveEventAlerts", () => {
  it("filters createAlert decisions and acknowledged entries", () => {
    notificationCenter.ingest(event("included", "ERROR"), decision);
    notificationCenter.ingest(event("not-alert", "WARNING"), { ...decision, createAlert: false });
    notificationCenter.ingest(event("acknowledged", "CRITICAL"), {
      ...decision,
      dedupeKey: "acknowledged",
    });
    notificationCenter.acknowledge("acknowledged");

    expect(useActiveEventAlerts().map((alert) => alert.id)).toEqual(["alert-included"]);
  });

  it.each([
    ["CRITICAL", "CRITICAL"],
    ["ERROR", "HIGH"],
    ["WARNING", "MEDIUM"],
  ] as const)("maps %s event severity to %s alert severity", (eventSeverity, alertSeverity) => {
    notificationCenter.ingest(event(eventSeverity, eventSeverity), decision);

    expect(useActiveEventAlerts()[0]?.severity).toBe(alertSeverity);
  });

  it("extracts alert fields while preserving diagnostic payload", () => {
    notificationCenter.ingest(event("fields", "ERROR"), decision);

    expect(useActiveEventAlerts()[0]).toMatchObject({
      id: "alert-fields",
      title: "Alert fields",
      description: "Description fields",
      suggestedAction: "Review fields",
      source: "LOCAL_RUNTIME",
      createdAt: "2026-07-23T00:00:00Z",
    });
    expect(notificationCenter.list()[0]?.latest.payload).toMatchObject({
      ticket: 42,
      magic: 9001,
      expected: "READY",
    });
  });
});
