import { beforeEach, describe, expect, it } from "vitest";
import {
  tradeJournalStore,
  computeJournalStats,
  computeRHistogram,
} from "@/lib/runtime/domain/trade-journal";
import type { ClosedTrade } from "@/lib/types";

function makeTrade(overrides: Partial<ClosedTrade> = {}): ClosedTrade {
  return {
    tradeId: "t1",
    positionId: "p1",
    strategyId: "strat_x",
    symbol: "EURUSD",
    direction: "LONG",
    entryPrice: 1.1,
    exitPrice: 1.11,
    openedAt: "2026-07-11T10:00:00.000Z",
    closedAt: "2026-07-11T11:00:00.000Z",
    holdingSeconds: 3600,
    volumeInitial: 0.1,
    grossPnl: 20,
    commission: -1,
    swap: 0,
    netPnl: 19,
    rMultiple: 1.5,
    mfeR: 2,
    maeR: -0.5,
    exitReason: "TP",
    partialFills: [],
    tags: [],
    ...overrides,
  };
}

describe("trade journal store", () => {
  beforeEach(() => tradeJournalStore.reset());

  it("dedupes rows by tradeId across history batches", () => {
    tradeJournalStore.ingestHistory([makeTrade({ tradeId: "a", netPnl: 10, grossPnl: 11 })]);
    tradeJournalStore.ingestHistory([makeTrade({ tradeId: "a", netPnl: 12, grossPnl: 13 })]);
    const snap = tradeJournalStore.getSnapshot();
    expect(snap.trades).toHaveLength(1);
    // Second history write overwrites first because both originate from history.
    expect(snap.trades[0]?.netPnl).toBe(12);
  });

  it("live event wins over paginated history row for the same tradeId", () => {
    tradeJournalStore.ingestHistory([makeTrade({ tradeId: "b", netPnl: 5 })]);
    tradeJournalStore.ingestEvent(makeTrade({ tradeId: "b", netPnl: 999 }));
    const snap = tradeJournalStore.getSnapshot();
    expect(snap.trades).toHaveLength(1);
    expect(snap.trades[0]?.netPnl).toBe(999);
    expect(snap.overwrittenByEvent).toBe(1);
  });

  it("event stays authoritative — later history for same id does not overwrite it", () => {
    tradeJournalStore.ingestEvent(makeTrade({ tradeId: "c", netPnl: 100 }));
    tradeJournalStore.ingestHistory([makeTrade({ tradeId: "c", netPnl: 1 })]);
    const snap = tradeJournalStore.getSnapshot();
    expect(snap.trades[0]?.netPnl).toBe(100);
  });
});

describe("R-multiple null policy", () => {
  it("excludes null R from histogram and avgR but counts trades and netPnl", () => {
    const trades: ClosedTrade[] = [
      makeTrade({ tradeId: "1", rMultiple: 1.0, netPnl: 10 }),
      makeTrade({ tradeId: "2", rMultiple: -0.5, netPnl: -5 }),
      makeTrade({ tradeId: "3", rMultiple: null, netPnl: 3 }),
      makeTrade({ tradeId: "4", rMultiple: null, netPnl: -2 }),
    ];
    const stats = computeJournalStats(trades);
    expect(stats.total).toBe(4);
    expect(stats.netPnl).toBe(6);
    expect(stats.naR).toBe(2);
    expect(stats.rScored).toBe(2);
    expect(stats.avgR).toBeCloseTo((1.0 - 0.5) / 2, 8);

    const hist = computeRHistogram(trades);
    const totalInHist = hist.reduce((s, b) => s + b.count, 0);
    expect(totalInHist).toBe(2); // null R excluded from histogram
  });

  it("reports avgR as null when every trade has null R", () => {
    const trades = [
      makeTrade({ tradeId: "x", rMultiple: null }),
      makeTrade({ tradeId: "y", rMultiple: null }),
    ];
    const stats = computeJournalStats(trades);
    expect(stats.avgR).toBeNull();
    expect(stats.rScored).toBe(0);
    expect(stats.naR).toBe(2);
  });
});
