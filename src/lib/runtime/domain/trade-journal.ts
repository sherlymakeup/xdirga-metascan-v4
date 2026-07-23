// Trade Journal cache (Phase 5F.5).
//
// Purpose:
//   Single source of truth for CLOSED trades on the frontend. Feeds:
//     - Analytics summary (net PnL, win rate, R histogram, avg R)
//     - The Journal table (paginated view of closed trades)
//
// Data sources (both feed the same cache):
//   1. Live `trade.closed` events from the runtime event stream.
//   2. Paginated backfill via `RuntimeAdapter.getTradeHistory()`.
//
// Dedup rules (per spec):
//   * Dedup key is `tradeId`.
//   * On conflict, the LIVE EVENT WINS over the paginated backfill row —
//     the event is always the most recent truth.
//   * The in-memory cache is bounded at MAX_ROWS most-recent closed trades.
//     Older rows come from pagination on demand.
//
// R-multiple null policy:
//   * `rMultiple === null` trades ARE counted in trade counts and netPnl.
//   * They are EXCLUDED from the R-multiple histogram and from avgR.
//   * The summary reports an explicit `naR` count so nothing disappears.
//
// Sign convention (see src/lib/types.ts and HANDOFF.md):
//   netPnl === grossPnl + commission + swap  (addition, not subtraction).

import { useSyncExternalStore } from "react";
import type { ClosedTrade } from "@/lib/types";

const MAX_ROWS = 500;

type Listener = () => void;

interface JournalSnapshot {
  trades: ClosedTrade[];
  bySource: { events: number; history: number };
  overwrittenByEvent: number;
  lastUpdatedAt: string | null;
  nextCursor: string | null;
  loading: boolean;
  historyError: "History unavailable" | "History incomplete" | null;
  historyIncomplete: boolean;
}

class TradeJournalStore {
  private trades = new Map<string, { row: ClosedTrade; from: "event" | "history" }>();
  private listeners = new Set<Listener>();
  private overwrittenByEvent = 0;
  private lastUpdatedAt: string | null = null;
  private nextCursor: string | null = null;
  private loading = false;
  private historyError: JournalSnapshot["historyError"] = null;
  private historyIncomplete = false;
  private snapshotCache: JournalSnapshot = {
    trades: [],
    bySource: { events: 0, history: 0 },
    overwrittenByEvent: 0,
    lastUpdatedAt: null,
    nextCursor: null,
    loading: false,
    historyError: null,
    historyIncomplete: false,
  };

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  private recompute() {
    const arr = Array.from(this.trades.values());
    arr.sort((a, b) => new Date(b.row.closedAt).getTime() - new Date(a.row.closedAt).getTime());
    let events = 0;
    let history = 0;
    for (const t of arr) {
      if (t.from === "event") events++;
      else history++;
    }
    this.snapshotCache = {
      trades: arr.map((t) => t.row),
      bySource: { events, history },
      overwrittenByEvent: this.overwrittenByEvent,
      lastUpdatedAt: this.lastUpdatedAt,
      nextCursor: this.nextCursor,
      loading: this.loading,
      historyError: this.historyError,
      historyIncomplete: this.historyIncomplete,
    };
  }

  private emit() {
    this.recompute();
    for (const l of this.listeners) l();
  }

  private trim() {
    if (this.trades.size <= MAX_ROWS) return;
    const arr = Array.from(this.trades.entries()).sort(
      (a, b) => new Date(a[1].row.closedAt).getTime() - new Date(b[1].row.closedAt).getTime(),
    );
    while (this.trades.size > MAX_ROWS) {
      const oldest = arr.shift();
      if (!oldest) break;
      this.trades.delete(oldest[0]);
    }
  }

  /** Ingest a batch from paginated history. Never overwrites a row that
   * came from a live event. */
  ingestHistory(rows: ClosedTrade[]): void {
    let changed = false;
    for (const row of rows) {
      const existing = this.trades.get(row.tradeId);
      if (existing && existing.from === "event") continue; // event wins
      this.trades.set(row.tradeId, { row, from: "history" });
      changed = true;
    }
    if (changed) {
      this.trim();
      this.lastUpdatedAt = new Date().toISOString();
    }
    if (changed || this.historyError !== null || this.historyIncomplete) {
      this.historyError = null;
      this.historyIncomplete = false;
      this.emit();
    }
  }

  /** Ingest a single row from a live `trade.closed` event. Always wins. */
  ingestEvent(row: ClosedTrade): void {
    const existing = this.trades.get(row.tradeId);
    if (existing && existing.from === "history") {
      this.overwrittenByEvent++;
    }
    this.trades.set(row.tradeId, { row, from: "event" });
    this.trim();
    this.lastUpdatedAt = new Date().toISOString();
    this.emit();
  }

  getSnapshot = (): JournalSnapshot => this.snapshotCache;

  setNextCursor(cursor: string | null) {
    if (this.nextCursor === cursor) return;
    this.nextCursor = cursor;
    this.emit();
  }

  setLoading(loading: boolean) {
    if (this.loading === loading) return;
    this.loading = loading;
    this.emit();
  }

  setHistoryError(error: NonNullable<JournalSnapshot["historyError"]>) {
    if (this.historyError === error && this.historyIncomplete) return;
    this.historyError = error;
    this.historyIncomplete = true;
    this.emit();
  }

  clearHistoryError() {
    if (this.historyError === null && !this.historyIncomplete) return;
    this.historyError = null;
    this.historyIncomplete = false;
    this.emit();
  }

  getNextCursor(): string | null {
    return this.nextCursor;
  }

  reset() {
    this.trades.clear();
    this.overwrittenByEvent = 0;
    this.lastUpdatedAt = null;
    this.nextCursor = null;
    this.loading = false;
    this.historyError = null;
    this.historyIncomplete = false;
    this.emit();
  }
}

export const tradeJournalStore = new TradeJournalStore();

export function useTradeJournal(): JournalSnapshot {
  return useSyncExternalStore(
    tradeJournalStore.subscribe,
    tradeJournalStore.getSnapshot,
    tradeJournalStore.getSnapshot,
  );
}

// -----------------------------------------------------------------------------
// Pure statistics helpers. Split from the store so they are trivially testable.
// -----------------------------------------------------------------------------

export interface JournalStats {
  total: number;
  wins: number;
  losses: number;
  scratches: number;
  winRate: number;
  netPnl: number;
  grossPnl: number;
  commission: number;
  swap: number;
  /** Trades EXCLUDED from R-stats (rMultiple === null). Surfaced in UI. */
  naR: number;
  /** Trades INCLUDED in R-stats. */
  rScored: number;
  avgR: number | null;
  bestR: number | null;
  worstR: number | null;
}

export function computeJournalStats(trades: ClosedTrade[]): JournalStats {
  let wins = 0;
  let losses = 0;
  let scratches = 0;
  let netPnl = 0;
  let grossPnl = 0;
  let commission = 0;
  let swap = 0;
  let naR = 0;
  const rValues: number[] = [];

  for (const t of trades) {
    netPnl += t.netPnl;
    grossPnl += t.grossPnl;
    commission += t.commission;
    swap += t.swap;

    if (t.netPnl > 0) wins++;
    else if (t.netPnl < 0) losses++;
    else scratches++;

    if (t.rMultiple === null) naR++;
    else rValues.push(t.rMultiple);
  }

  const rScored = rValues.length;
  const rSum = rValues.reduce((a, b) => a + b, 0);
  const decided = wins + losses;
  return {
    total: trades.length,
    wins,
    losses,
    scratches,
    winRate: decided > 0 ? wins / decided : 0,
    netPnl,
    grossPnl,
    commission,
    swap,
    naR,
    rScored,
    avgR: rScored > 0 ? rSum / rScored : null,
    bestR: rScored > 0 ? Math.max(...rValues) : null,
    worstR: rScored > 0 ? Math.min(...rValues) : null,
  };
}

/** Fixed-bucket histogram in R. Buckets: (-inf,-2], (-2,-1], (-1,0], (0,1], (1,2], (2,+inf).
 *  Null R trades are EXCLUDED. */
export function computeRHistogram(trades: ClosedTrade[]): Array<{ label: string; count: number }> {
  const buckets = [
    { label: "≤ -2R", count: 0, test: (r: number) => r <= -2 },
    { label: "-2..-1R", count: 0, test: (r: number) => r > -2 && r <= -1 },
    { label: "-1..0R", count: 0, test: (r: number) => r > -1 && r <= 0 },
    { label: "0..1R", count: 0, test: (r: number) => r > 0 && r <= 1 },
    { label: "1..2R", count: 0, test: (r: number) => r > 1 && r <= 2 },
    { label: "> 2R", count: 0, test: (r: number) => r > 2 },
  ];
  for (const t of trades) {
    if (t.rMultiple === null) continue;
    const b = buckets.find((x) => x.test(t.rMultiple as number));
    if (b) b.count++;
  }
  return buckets.map(({ label, count }) => ({ label, count }));
}
