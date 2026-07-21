import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const route = readFileSync(new URL("../../../routes/positions.tsx", import.meta.url), "utf8");
const cockpit = readFileSync(new URL("../../../routes/index.tsx", import.meta.url), "utf8");
const scenarios = readFileSync(new URL("../../demo/scenarios.ts", import.meta.url), "utf8");

describe("authoritative dashboard UI", () => {
  it("gates command controls by explicit demo mode", () => {
    expect(route).toContain("const isDemo = getRuntimeMode() === \"fixture\"");
    expect(route).toContain("isDemo &&");
    expect(cockpit).toContain("const isDemo = getRuntimeMode() === \"fixture\"");
    expect(cockpit).toContain("isDemo &&");
  });

  it("renders every position ownership and makes non-bot rows read-only", () => {
    expect(route).toContain("p.ownership");
    expect(route).toContain("p.ownership === \"BOT_MANAGED\"");
    expect(route).toContain("Read-only");
  });

  it("uses backend domain availability instead of nullable fields", () => {
    expect(cockpit).toContain("snap.accountAvailable");
    expect(cockpit).not.toContain("floatingPnl == null ? \"Unavailable\"");
  });

  it("does not fabricate unavailable account aggregates or observation time", () => {
    const empty = scenarios.slice(scenarios.indexOf("export function createEmptySnapshot"));
    expect(empty).toContain("floatingPnl: null");
    expect(empty).toContain("openPositions: null");
    expect(empty).toContain("updatedAt: null");
    expect(empty).not.toContain("accountUnavailableAt");
    expect(cockpit).toContain("snap.account.updatedAt ? relativeTime(snap.account.updatedAt) : \"—\"");
    expect(empty).not.toContain("const t = new Date().toISOString()");
  });
});
