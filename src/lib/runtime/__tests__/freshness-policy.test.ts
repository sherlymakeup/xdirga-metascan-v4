import { describe, it, expect } from "vitest";
import {
  classifyFreshness,
  restrictionFor,
  commandsBlockedByRestriction,
} from "../state/freshness-policy";

describe("freshness-policy", () => {
  it("classifies domains against configured thresholds", () => {
    expect(classifyFreshness("marketData", 500)).toBe("FRESH");
    expect(classifyFreshness("marketData", 2500)).toBe("DELAYED");
    expect(classifyFreshness("marketData", 6000)).toBe("STALE");
    expect(classifyFreshness("marketData", null)).toBe("UNAVAILABLE");
  });

  it("maps stale market data to TRADING_BLOCKED", () => {
    expect(restrictionFor("marketData", "STALE")).toBe("TRADING_BLOCKED");
    expect(restrictionFor("risk", "STALE")).toBe("ENTRIES_BLOCKED");
    expect(restrictionFor("risk", "FRESH")).toBe("NONE");
  });

  it("safety commands are never blocked by staleness", () => {
    const blocked = commandsBlockedByRestriction("TRADING_BLOCKED");
    for (const safety of [
      "safety.kill",
      "runtime.pause",
      "runtime.disableEntries",
      "position.close",
      "order.cancel",
    ] as const) {
      expect(blocked).not.toContain(safety);
    }
  });

  it("TRADING_BLOCKED is a superset of ENTRIES_BLOCKED", () => {
    const entries = commandsBlockedByRestriction("ENTRIES_BLOCKED");
    const trading = commandsBlockedByRestriction("TRADING_BLOCKED");
    for (const k of entries) expect(trading).toContain(k);
    expect(trading.length).toBeGreaterThan(entries.length);
  });
});
