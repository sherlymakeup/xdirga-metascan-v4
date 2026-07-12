import { describe, it, expect } from "vitest";
import { EventDeduplicator } from "../events/event-deduplicator";
import type { RuntimeEventEnvelope } from "../events/runtime-event-envelope";

function env(
  overrides: Partial<RuntimeEventEnvelope> & {
    eventId: string;
    sequence: number;
  },
): RuntimeEventEnvelope {
  return {
    type: "runtime.state.changed",
    runtimeId: "rt-1",
    bootId: "boot-A",
    revision: 1,
    occurredAt: "2026-01-01T00:00:00Z",
    emittedAt: "2026-01-01T00:00:00Z",
    receivedAt: "2026-01-01T00:00:00Z",
    severity: "INFO",
    source: "DEVELOPMENT_FIXTURE",
    payload: {},
    ...overrides,
  };
}

describe("EventDeduplicator", () => {
  it("accepts the first event and then contiguous sequences", () => {
    const d = new EventDeduplicator();
    expect(d.evaluate(env({ eventId: "e1", sequence: 1 })).action).toBe("accept");
    expect(d.evaluate(env({ eventId: "e2", sequence: 2 })).action).toBe("accept");
  });

  it("drops duplicate ids and older sequences", () => {
    const d = new EventDeduplicator();
    d.evaluate(env({ eventId: "e1", sequence: 5 }));
    expect(d.evaluate(env({ eventId: "e1", sequence: 6 })).action).toBe("drop");
    expect(d.evaluate(env({ eventId: "e-old", sequence: 4 })).action).toBe("drop");
  });

  it("reports gaps with correct span", () => {
    const d = new EventDeduplicator();
    d.evaluate(env({ eventId: "e1", sequence: 1 }));
    const out = d.evaluate(env({ eventId: "e5", sequence: 5 }));
    expect(out.action).toBe("gap");
    if (out.action === "gap") {
      expect(out.from).toBe(2);
      expect(out.to).toBe(4);
      expect(out.missing).toBe(3);
    }
  });

  it("resets on newer bootId and rejects obsolete boot", () => {
    const d = new EventDeduplicator();
    d.evaluate(env({ eventId: "e1", sequence: 10, bootId: "boot-B" }));
    const reset = d.evaluate(
      env({ eventId: "e-new", sequence: 1, bootId: "boot-C" }),
    );
    expect(reset.action).toBe("reset-boot");
    const obsolete = d.evaluate(
      env({ eventId: "e-old-boot", sequence: 99, bootId: "boot-A" }),
    );
    expect(obsolete.action).toBe("drop");
  });
});
