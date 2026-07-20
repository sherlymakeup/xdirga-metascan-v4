// Sign convention (Phase 5F.5): commission and swap are SIGNED values as
// reported by MT5 (costs are negative). Identity that MUST hold on every
// position and every closed trade: netPnl = grossPnl + commission + swap
// (addition, not subtraction).

import { describe, expect, it } from "vitest";
import { buildSnapshot, getAllFixtureTrades } from "@/lib/demo/scenarios";
import { marketPulse } from "@/routes/markets";

describe("sign convention: net = gross + commission + swap", () => {
  it("holds on every open position (floatingPnl + commission + swap = netPnl)", () => {
    const snap = buildSnapshot("healthy");
    expect(snap.positions.length).toBeGreaterThan(0);
    for (const p of snap.positions) {
      const expected = p.floatingPnl + p.commission + p.swap;
      expect(p.netPnl).toBeCloseTo(expected, 8);
    }
  });

  it("holds on every closed trade in the fixture journal", () => {
    const trades = getAllFixtureTrades();
    expect(trades.length).toBeGreaterThan(0);
    for (const t of trades) {
      const expected = t.grossPnl + t.commission + t.swap;
      expect(t.netPnl).toBeCloseTo(expected, 8);
    }
  });

  it("commissions are non-positive across the fixture (costs are negative)", () => {
    const trades = getAllFixtureTrades();
    for (const t of trades) {
      expect(t.commission).toBeLessThanOrEqual(0);
    }
  });
});

describe("market change availability", () => {
  it("excludes null changes from direction and breadth", () => {
    const snap = buildSnapshot("healthy");
    const fx = marketPulse(snap.markets).find((item) => item.group === "FX")!;

    expect(snap.markets.some((market) => market.changePct === null)).toBe(true);
    expect(fx.observed).toBe(fx.up + fx.down);
    expect(fx.observed).toBeLessThan(fx.total);
    expect(fx.breadthPct).toBe((fx.up / fx.observed) * 100);
  });

  it("uses deterministic fixture provenance", () => {
    const first = buildSnapshot("healthy");
    const second = buildSnapshot("healthy");

    expect(first.positionsObservedAt).toBe(second.positionsObservedAt);
    expect(first.accountObservedAt).toBe(second.accountObservedAt);
  });
});
