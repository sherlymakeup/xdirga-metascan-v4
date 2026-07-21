import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const route = readFileSync(new URL("../../../routes/positions.tsx", import.meta.url), "utf8");
const cockpit = readFileSync(new URL("../../../routes/index.tsx", import.meta.url), "utf8");
const events = readFileSync(new URL("../../../routes/events.tsx", import.meta.url), "utf8");
const statusBar = readFileSync(
  new URL("../../../components/cockpit/top-status-bar.tsx", import.meta.url),
  "utf8",
);
const scenarios = readFileSync(new URL("../../demo/scenarios.ts", import.meta.url), "utf8");

describe("authoritative dashboard UI", () => {
  it("gates command controls by explicit demo mode", () => {
    expect(route).toContain('const isDemo = getRuntimeMode() === "fixture"');
    expect(route).toContain("isDemo &&");
    expect(cockpit).toContain('const isDemo = getRuntimeMode() === "fixture"');
    expect(cockpit).toContain("isDemo &&");
  });

  it("renders every position ownership and makes non-bot rows read-only", () => {
    expect(route).toContain("p.ownership");
    expect(route).toContain('p.ownership === "BOT_MANAGED"');
    expect(route).toContain("Read-only");
  });

  it("uses backend domain availability instead of nullable fields", () => {
    expect(cockpit).toContain("snap.accountAvailable");
    expect(cockpit).not.toContain('floatingPnl == null ? "Unavailable"');
  });

  it("does not fabricate unavailable account aggregates or observation time", () => {
    const empty = scenarios.slice(scenarios.indexOf("export function createEmptySnapshot"));
    expect(empty).toContain("floatingPnl: null");
    expect(empty).toContain("openPositions: null");
    expect(empty).toContain("updatedAt: null");
    expect(empty).not.toContain("accountUnavailableAt");
    expect(cockpit).toContain(
      'snap.account.updatedAt ? relativeTime(snap.account.updatedAt) : "—"',
    );
    expect(empty).not.toContain("const t = new Date().toISOString()");
  });

  it("uses null disconnected telemetry and suppresses unavailable account metrics", () => {
    const empty = scenarios.slice(scenarios.indexOf("export function createEmptySnapshot"));
    expect(empty).toContain("startedAt: null");
    expect(empty).toContain("uptimeSec: null");
    expect(empty).toContain("lastHeartbeatAt: null");
    expect(empty).toContain("heartbeatLatencyMs: null");
    expect(empty).toContain("lastRequestAt: null");
    expect(empty).toContain("avgLatencyMs: null");
    expect(empty).toContain("balance: null");
    expect(empty).not.toContain("1970-01-01T00:00:00.000Z");
    expect(cockpit).toContain("const accountAvailable = snap.accountAvailable");
    expect(cockpit).toContain('value={accountAvailable ? fmtMoney(snap.account.balance) : "—"}');
  });

  it("marks retained positions stale without current-state tone or actions", () => {
    expect(route).toContain("const stale = !p.dataAvailable");
    expect(route).toContain("STALE");
    expect(route).toContain('positionsObservedAt ? fmtDateTime(positionsObservedAt) : "N/A"');
    expect(route).toContain('stale ? "" : p.floatingPnl >= 0 ? "text-profit" : "text-loss"');
    expect(route).toContain("const positionsAvailable = snap.positionsAvailable");
  });

  it("keeps legacy acknowledgement controls fixture-only", () => {
    expect(events).toContain('const isDemo = getRuntimeMode() === "fixture"');
    expect(events).toContain("selected.acknowledged ? (");
    expect(events).toContain("isDemo ? (");
    expect(events).not.toContain("onClick={ackAll}");
  });

  it("handles absent runtime and broker telemetry", () => {
    expect(statusBar).toContain("const heartbeatAge = snap.runtime.lastHeartbeatAt");
    expect(statusBar).toContain('snap.broker.avgLatencyMs == null ? "—"');
    expect(statusBar).toContain('snap.runtime.uptimeSec == null ? "—"');
  });
});
