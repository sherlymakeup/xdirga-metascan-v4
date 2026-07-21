import { describe, it, expect } from "vitest";
import { validateTransition, isTerminalState } from "../commands/command-transitions";

describe("command-transitions", () => {
  it("allows canonical happy-path progression", () => {
    for (const [from, to] of [
      ["PREPARED", "SUBMITTING"],
      ["SUBMITTING", "ACCEPTED"],
      ["ACCEPTED", "ACKNOWLEDGED"],
      ["ACKNOWLEDGED", "IN_PROGRESS"],
      ["IN_PROGRESS", "COMPLETED"],
    ] as const) {
      expect(validateTransition(from, to).ok).toBe(true);
    }
  });

  it("rejects skipping straight from PREPARED to ACCEPTED", () => {
    expect(validateTransition("PREPARED", "ACCEPTED").ok).toBe(false);
  });

  it("blocks transitions out of terminal states", () => {
    for (const term of [
      "COMPLETED",
      "FAILED",
      "TIMED_OUT",
      "EXECUTION_UNKNOWN",
      "CANCELLED",
    ] as const) {
      expect(isTerminalState(term)).toBe(true);
      expect(validateTransition(term, "IN_PROGRESS").ok).toBe(false);
    }
  });

  it("permits SUBMITTING → EXECUTION_UNKNOWN (broker ambiguity)", () => {
    expect(validateTransition("SUBMITTING", "EXECUTION_UNKNOWN").ok).toBe(true);
  });

  it("no-op transitions (same → same) are allowed", () => {
    expect(validateTransition("IN_PROGRESS", "IN_PROGRESS").ok).toBe(true);
  });
});
