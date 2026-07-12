// Bootstraps the event pipeline in the browser. Wires the active runtime
// adapter's event stream AND (when available) the Development Fixture Event
// Source into the router. Safe to call multiple times.

import { getFixtureEventSource } from "./fixture-event-source";
import { routeEvent } from "./event-router";
import { getRuntimeAdapter } from "../index";
import { bootstrapDomainProjections } from "../domain/projections";
import { snapshotHydrationStore } from "../state/snapshot-hydration";
import { convergenceStore } from "../state/convergence";
import { tradeJournalStore } from "../domain/trade-journal";
import type { ClosedTrade } from "@/lib/types";

let bootstrapped = false;
const unsubscribers: Array<() => void> = [];

export function bootstrapEventPipeline() {
  if (bootstrapped) return;
  bootstrapped = true;
  if (typeof window === "undefined") return;

  const adapter = getRuntimeAdapter();

  // Route ALL adapter-emitted events (both fixture and live runtimes) through
  // the same pipeline so downstream projections/notifications share one path.
  unsubscribers.push(
    adapter.subscribeEvents((env) => {
      routeEvent(env);
      // Journal: live trade.closed events feed the journal cache directly.
      // Sign convention enforced by the payload schema (see event-schemas.ts).
      if (env.type === "trade.closed") {
        const p = env.payload as Partial<ClosedTrade> | undefined;
        if (p && p.tradeId && typeof p.netPnl === "number") {
          tradeJournalStore.ingestEvent(p as ClosedTrade);
        }
      }
    }),
  );

  // Additional deterministic scenario emitter — fixture only.
  if (adapter.adapterType === "fixture") {
    const source = getFixtureEventSource();
    unsubscribers.push(source.subscribe((env) => routeEvent(env)));
    source.start().catch(() => {});
  }

  // Domain projections subscribe to the shared event history store.
  bootstrapDomainProjections();

  // Snapshot hydration/convergence — subscribe to adapter snapshots.
  snapshotHydrationStore.bootstrap();
  convergenceStore.bootstrap();

  // Prime the trade journal with a first page of history so the Analytics
  // page has data even before any live trade.closed events arrive.
  tradeJournalStore.setLoading(true);
  void adapter
    .getTradeHistory({ limit: 100 })
    .then((page) => {
      tradeJournalStore.ingestHistory(page.trades);
      tradeJournalStore.setNextCursor(page.nextCursor);
    })
    .catch(() => {
      /* HttpRuntimeAdapter safe-fails with an empty page. */
    })
    .finally(() => tradeJournalStore.setLoading(false));
}

/**
 * Fetch the next page of closed-trade history (cursor pagination). Safe to
 * call multiple times; no-ops if there is no cursor or a load is in flight.
 */
export async function loadMoreTradeHistory(limit = 100): Promise<void> {
  const snap = tradeJournalStore.getSnapshot();
  if (snap.loading || !snap.nextCursor) return;
  const adapter = getRuntimeAdapter();
  tradeJournalStore.setLoading(true);
  try {
    const page = await adapter.getTradeHistory({ cursor: snap.nextCursor, limit });
    tradeJournalStore.ingestHistory(page.trades);
    tradeJournalStore.setNextCursor(page.nextCursor);
  } catch {
    /* ignore */
  } finally {
    tradeJournalStore.setLoading(false);
  }
}

export function teardownEventPipeline() {
  if (!bootstrapped) return;
  for (const u of unsubscribers) {
    try {
      u();
    } catch {
      /* ignore */
    }
  }
  unsubscribers.length = 0;
  bootstrapped = false;
  getFixtureEventSource().stop().catch(() => {});
}

