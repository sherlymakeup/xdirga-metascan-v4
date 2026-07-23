import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tradeJournalStore } from "@/lib/runtime/domain/trade-journal";

const adapter = {
  adapterType: "http",
  subscribeEvents: vi.fn(() => () => {}),
  getTradeHistory: vi.fn(),
};

vi.mock("@/lib/runtime", () => ({ getRuntimeAdapter: () => adapter }));
vi.mock("@/lib/runtime/events/fixture-event-source", () => ({
  getFixtureEventSource: () => ({
    subscribe: () => () => {},
    start: () => Promise.resolve(),
    stop: () => Promise.resolve(),
  }),
}));
vi.mock("@/lib/runtime/events/event-router", () => ({ routeEvent: vi.fn() }));
vi.mock("@/lib/runtime/domain/projections", () => ({ bootstrapDomainProjections: vi.fn() }));
vi.mock("@/lib/runtime/state/snapshot-hydration", () => ({
  snapshotHydrationStore: { bootstrap: vi.fn() },
}));
vi.mock("@/lib/runtime/state/convergence", () => ({ convergenceStore: { bootstrap: vi.fn() } }));

import {
  bootstrapEventPipeline,
  loadMoreTradeHistory,
  teardownEventPipeline,
} from "@/lib/runtime/events/bootstrap";

describe("trade-history bootstrap", () => {
  beforeEach(() => {
    vi.stubGlobal("window", {});
    tradeJournalStore.reset();
    adapter.getTradeHistory.mockReset();
  });

  afterEach(() => {
    teardownEventPipeline();
    vi.unstubAllGlobals();
  });

  it("marks initial history unavailable when its request fails", async () => {
    adapter.getTradeHistory.mockRejectedValueOnce(new Error("offline"));
    bootstrapEventPipeline();
    await vi.waitFor(() =>
      expect(tradeJournalStore.getSnapshot().historyError).toBe("History unavailable"),
    );
    expect(tradeJournalStore.getSnapshot().historyIncomplete).toBe(true);
  });

  it("marks paginated history incomplete when load more fails", async () => {
    tradeJournalStore.setNextCursor("next");
    adapter.getTradeHistory.mockRejectedValueOnce(new Error("offline"));
    await loadMoreTradeHistory();
    expect(tradeJournalStore.getSnapshot().historyError).toBe("History incomplete");
    expect(tradeJournalStore.getSnapshot().historyIncomplete).toBe(true);
  });
});
