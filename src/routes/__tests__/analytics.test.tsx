import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { tradeJournalStore } from "@/lib/runtime/domain/trade-journal";
import type { ClosedTrade } from "@/lib/types";

const snapshot = {
  current: {
    account: {
      realizedPnlToday: 0,
      realizedPnlWeek: 0,
      winRate: 0,
      profitFactor: 0,
      tradesToday: 0,
      maxDrawdown: 0,
    },
    equityCurve: [],
    strategies: [],
  },
};

vi.mock("@/lib/adapters/runtime", () => ({ useSnapshot: () => snapshot.current }));
vi.mock("@/lib/runtime/events/bootstrap", () => ({ loadMoreTradeHistory: vi.fn() }));

import { AnalyticsPage } from "../analytics";

function trade(overrides: Partial<ClosedTrade> = {}): ClosedTrade {
  return {
    tradeId: "trade-1",
    positionId: "position-1",
    strategyId: "strategy-1",
    symbol: "EURUSD",
    direction: "LONG",
    entryPrice: 1,
    exitPrice: 2,
    openedAt: "2026-07-01T00:00:00.000Z",
    closedAt: "2026-07-01T01:00:00.000Z",
    holdingSeconds: 1,
    volumeInitial: 1,
    grossPnl: 1,
    commission: 0,
    swap: 0,
    netPnl: 1,
    rMultiple: 1,
    mfeR: 1,
    maeR: 0,
    exitReason: "TP",
    partialFills: [],
    tags: [],
    ...overrides,
  };
}

describe("AnalyticsPage journal status", () => {
  beforeEach(() => tradeJournalStore.reset());

  it("renders unavailable history and row verification states", () => {
    tradeJournalStore.setHistoryError("History unavailable");
    tradeJournalStore.ingestHistory([
      trade({ tradeId: "unverified", tags: ["sp3-no-history"] }),
      trade({ tradeId: "reconciled", tags: ["deal-reconciled"] }),
      trade({ tradeId: "unknown" }),
    ]);
    tradeJournalStore.setHistoryError("History unavailable");

    const html = renderToStaticMarkup(<AnalyticsPage />);

    expect(html).toContain("History unavailable");
    expect(html).toContain("Unverified");
    expect(html).toContain("Deal reconciled");
    expect(html).toContain("Unknown");
    expect(html).not.toContain("Verified");
  });
});
