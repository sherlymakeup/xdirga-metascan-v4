import { describe, it, expect } from "vitest";
import { EventDeduplicator } from "../events/event-deduplicator";
import { resetEventRouter, resetEventRouterToSnapshot, routeEvent } from "../events/event-router";
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

  it.each([
    ["f0000000-0000-4000-8000-000000000000", "10000000-0000-4000-8000-000000000000"],
    ["10000000-0000-4000-8000-000000000000", "f0000000-0000-4000-8000-000000000000"],
  ])("accepts a foreign UUID boot regardless of lexical order", (currentBootId, nextBootId) => {
    const d = new EventDeduplicator();
    d.evaluate(env({ eventId: "current", sequence: 10, bootId: currentBootId }));

    expect(d.evaluate(env({ eventId: "next", sequence: 1, bootId: nextBootId }))).toEqual({
      action: "reset-boot",
      previousBootId: currentBootId,
      newBootId: nextBootId,
    });
    expect(d.evaluate(env({ eventId: "straggler", sequence: 11, bootId: currentBootId }))).toEqual({
      action: "drop",
      reason: "obsolete-boot",
    });
  });

  it("seeds the stateful event router from an authoritative snapshot", () => {
    resetEventRouter();
    expect(routeEvent(env({ eventId: "old", sequence: 10, bootId: "old-boot" })).accepted).toBe(
      true,
    );

    resetEventRouterToSnapshot("rt-1", "new-boot", 20);

    expect(routeEvent(env({ eventId: "straggler", sequence: 11, bootId: "old-boot" }))).toEqual({
      accepted: false,
      reason: "obsolete-boot",
    });
    expect(routeEvent(env({ eventId: "current", sequence: 21, bootId: "new-boot" })).accepted).toBe(
      true,
    );
    resetEventRouter();
  });

  it("evicts superseded boots FIFO without evicting the active boot or exceeding 32", () => {
    const d = new EventDeduplicator();
    const boots = Array.from(
      { length: 34 },
      (_, index) => `${index.toString(16).padStart(8, "0")}-0000-4000-8000-000000000000`,
    );
    d.evaluate(env({ eventId: "boot-0", sequence: 1, bootId: boots[0] }));
    for (let index = 1; index < boots.length; index += 1) {
      expect(
        d.evaluate(env({ eventId: `boot-${index}`, sequence: 1, bootId: boots[index] })).action,
      ).toBe("reset-boot");
    }

    expect(d.evaluate(env({ eventId: "oldest", sequence: 2, bootId: boots[0] })).action).toBe(
      "reset-boot",
    );
    expect(d.evaluate(env({ eventId: "active", sequence: 3, bootId: boots[0] })).action).toBe(
      "accept",
    );
    expect(
      d.evaluate(env({ eventId: "second-evicted", sequence: 2, bootId: boots[1] })).action,
    ).toBe("reset-boot");
    expect(d.evaluate(env({ eventId: "still-retained", sequence: 2, bootId: boots[3] }))).toEqual({
      action: "drop",
      reason: "obsolete-boot",
    });
  });
});
