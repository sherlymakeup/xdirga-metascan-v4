// Phase 5D — centralized data freshness policy.
// All routes/panels MUST read thresholds from here. Placeholder values suitable
// for the DEVELOPMENT_FIXTURE source; the LOCAL_RUNTIME backend may later
// override at runtime through a config channel.

import type { RuntimeCommandKind } from "../runtime-types";

export type FreshnessDomain =
  | "runtime"
  | "broker"
  | "marketData"
  | "account"
  | "orders"
  | "positions"
  | "risk"
  | "reconciliation";

export interface FreshnessThresholds {
  delayedAfterMs: number;
  staleAfterMs: number;
}

export const FRESHNESS_POLICY: Readonly<Record<FreshnessDomain, FreshnessThresholds>> = {
  runtime: { delayedAfterMs: 5_000, staleAfterMs: 15_000 },
  broker: { delayedAfterMs: 3_000, staleAfterMs: 10_000 },
  marketData: { delayedAfterMs: 2_000, staleAfterMs: 5_000 },
  account: { delayedAfterMs: 5_000, staleAfterMs: 15_000 },
  orders: { delayedAfterMs: 5_000, staleAfterMs: 15_000 },
  positions: { delayedAfterMs: 5_000, staleAfterMs: 15_000 },
  risk: { delayedAfterMs: 5_000, staleAfterMs: 15_000 },
  reconciliation: { delayedAfterMs: 30_000, staleAfterMs: 120_000 },
} as const;

export type FreshnessLevel = "FRESH" | "DELAYED" | "STALE" | "UNAVAILABLE";

export function classifyFreshness(
  domain: FreshnessDomain,
  ageMs: number | null | undefined,
): FreshnessLevel {
  if (ageMs == null || Number.isNaN(ageMs)) return "UNAVAILABLE";
  const t = FRESHNESS_POLICY[domain];
  if (ageMs >= t.staleAfterMs) return "STALE";
  if (ageMs >= t.delayedAfterMs) return "DELAYED";
  return "FRESH";
}

/**
 * Restrictions derived from a freshness level per domain. UI must gate commands
 * from this map; do not invent local rules.
 */
export type FreshnessRestriction = "NONE" | "WARNING" | "ENTRIES_BLOCKED" | "TRADING_BLOCKED";

export function restrictionFor(
  domain: FreshnessDomain,
  level: FreshnessLevel,
): FreshnessRestriction {
  if (level === "FRESH") return "NONE";
  if (level === "DELAYED") return "WARNING";
  // STALE / UNAVAILABLE
  if (domain === "marketData" || domain === "broker") return "TRADING_BLOCKED";
  if (domain === "risk" || domain === "account" || domain === "runtime") return "ENTRIES_BLOCKED";
  return "WARNING";
}

/**
 * Command kinds blocked when a given restriction is active. Read-only or
 * safety commands (kill, cancel, close, pause) are intentionally never blocked
 * by stale data — they exist to reduce exposure.
 */
export function commandsBlockedByRestriction(
  restriction: FreshnessRestriction,
): RuntimeCommandKind[] {
  if (restriction === "NONE" || restriction === "WARNING") return [];
  const entryBlocked: RuntimeCommandKind[] = [
    "runtime.enableEntries",
    "runtime.resume",
    "runtime.start",
    "strategy.resume",
    "config.apply",
  ];
  if (restriction === "ENTRIES_BLOCKED") return entryBlocked;
  // TRADING_BLOCKED — cannot place new orders/protection changes either.
  return [...entryBlocked, "position.modifyProtection"];
}
