import { useEffect, useState } from "react";
import { AlertTriangle, Clock, Menu } from "lucide-react";
import { NotificationCenterButton } from "@/components/runtime/NotificationCenter";
import {
  hydrateScenarioFromStorage,
  useScenario,
  useSnapshot,
  getRuntimeAdapter,
} from "@/lib/adapters/runtime";
import { getRuntimeMode } from "@/lib/runtime";
import { SCENARIOS } from "@/lib/demo/scenarios";
import { fmtDuration, fmtTime, relativeTime } from "@/lib/format";
import { PRODUCT_BRAND } from "@/lib/constants/brand";
import { RuntimeStateBadge } from "./runtime-state-badge";
import { StatusBadge } from "./status-badge";
import { CommandCenterButton } from "@/components/commands/CommandCenter";
import {
  BrokerConnectionBadge,
  BrokerEnvironmentBadge,
  BrokerTargetBadge,
  DataSourceBadge,
  ExecutionSemanticsBadge,
  LocalRuntimeConnectionBadge,
} from "@/components/runtime/environment-badges";
import type { ScenarioKey } from "@/lib/types";
import { DEVELOPMENT_FEATURES_ENABLED } from "@/lib/runtime/dev-flags";
import { useEventHistory } from "@/lib/runtime/events/event-store";

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function TopStatusBar({ onToggleSidebar }: { onToggleSidebar?: () => void }) {
  const snap = useSnapshot();
  const scenario = useScenario();
  const events = useEventHistory();
  const now = useNow();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    hydrateScenarioFromStorage();
    setHydrated(true);
  }, []);

  const heartbeatAge = snap.runtime.lastHeartbeatAt
    ? Math.max(
        0,
        Math.round((Date.now() - new Date(snap.runtime.lastHeartbeatAt).getTime()) / 1000),
      )
    : null;
  const brokerLatency = snap.broker.avgLatencyMs == null ? "—" : `${snap.broker.avgLatencyMs}ms`;
  const uptime = snap.runtime.uptimeSec == null ? "—" : fmtDuration(snap.runtime.uptimeSec);
  const healthTransition = events.find((event) => {
    if (event.type !== "runtime.health.changed" || !event.payload || typeof event.payload !== "object") {
      return false;
    }
    return (event.payload as { state?: unknown }).state === snap.runtime.state;
  });
  const healthPayload = healthTransition?.payload as { reasons?: unknown } | undefined;
  const healthReasons = Array.isArray(healthPayload?.reasons)
    ? healthPayload.reasons.filter((reason): reason is string => typeof reason === "string")
    : [];
  const changedAt = snap.runtime.stateChangedAt ?? healthTransition?.receivedAt;

  return (
    <header className="sticky top-0 z-30 border-b border-panel-border bg-background/95 backdrop-blur">
      {/* Row 1 */}
      <div className="flex h-11 items-center gap-2 px-3 md:px-4">
        {/* Mobile: menu + brand */}
        <div className="flex min-w-0 items-center gap-2 md:hidden">
          <button
            onClick={onToggleSidebar}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-panel-border bg-panel-elevated text-muted-foreground active:bg-muted"
            aria-label="Toggle sidebar"
          >
            <Menu className="h-4 w-4" />
          </button>
          <div className="flex min-w-0 items-center gap-2">
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-sm bg-primary/15 text-[10px] font-bold text-primary">
              X
            </span>
            <div className="min-w-0 leading-tight">
              <div className="truncate text-[12px] font-semibold tracking-tight">
                {PRODUCT_BRAND.name}
              </div>
              <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
                {PRODUCT_BRAND.category}
              </div>
            </div>
          </div>
        </div>

        {/* Desktop status cluster */}
        <div className="hidden md:flex min-w-0 items-center gap-2 overflow-x-auto scrollbar-none">
          <RuntimeStateBadge state={snap.runtime.state} />
          <DataSourceBadge />
          <LocalRuntimeConnectionBadge />
          <BrokerTargetBadge />
          <BrokerEnvironmentBadge />
          <BrokerConnectionBadge />
          <ExecutionSemanticsBadge />
          <StatusBadge
            tone={
              snap.account.freshness === "FRESH"
                ? "ok"
                : snap.account.freshness === "STALE"
                  ? "crit"
                  : "warn"
            }
          >
            Data {snap.account.freshness}
          </StatusBadge>
          <StatusBadge tone={snap.runtime.entriesEnabled ? "ok" : "warn"}>
            Entries {snap.runtime.entriesEnabled ? "ON" : "OFF"}
          </StatusBadge>
        </div>

        <div className="ml-auto hidden lg:flex items-center gap-4 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            <span className="num">{hydrated ? fmtTime(now.toISOString()) : "--:--:--"}</span>
            <span className="text-muted-foreground/70">local</span>
          </span>
          <span className="num">↔ {brokerLatency}</span>
          <span>
            hb {hydrated && heartbeatAge != null ? `${heartbeatAge}s` : "—"} · uptime{" "}
            {hydrated ? uptime : "—"}
          </span>
        </div>

        <div className="ml-auto md:ml-2 flex items-center gap-1.5">
          <CommandCenterButton />
          <NotificationCenterButton />
          {DEVELOPMENT_FEATURES_ENABLED && getRuntimeMode() === "fixture" && (
            <ScenarioSwitcher scenario={scenario} />
          )}
        </div>
      </div>

      {/* Row 2 — mobile-only status strip */}
      <div className="md:hidden border-t border-panel-border/60">
        <div className="scroll-fade-x scrollbar-none flex items-center gap-1.5 overflow-x-auto px-3 py-1.5">
          <RuntimeStateBadge state={snap.runtime.state} />
          <DataSourceBadge />
          <LocalRuntimeConnectionBadge />
          <BrokerTargetBadge />
          <BrokerEnvironmentBadge />
          <BrokerConnectionBadge />
          <ExecutionSemanticsBadge />
          <StatusBadge tone={snap.runtime.entriesEnabled ? "ok" : "warn"}>
            Entries {snap.runtime.entriesEnabled ? "ON" : "OFF"}
          </StatusBadge>
          <StatusBadge
            tone={
              snap.account.freshness === "FRESH"
                ? "ok"
                : snap.account.freshness === "STALE"
                  ? "crit"
                  : "warn"
            }
          >
            Data {snap.account.freshness}
          </StatusBadge>
          <span className="ml-1 inline-flex shrink-0 items-center gap-2 rounded-md border border-panel-border bg-panel-elevated px-2 py-1 text-[10px] text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span className="num text-foreground/90">
              {hydrated ? fmtTime(now.toISOString()) : "--:--:--"}
            </span>
            <span className="num">↔{brokerLatency}</span>
          </span>
        </div>
      </div>

      <div
        data-status-strip
        className={`flex h-7 items-center gap-2 border-t px-3 text-[11.5px] md:px-4 ${
          snap.runtime.state === "KILLED" || snap.runtime.state === "ERROR"
            ? "border-status-crit/40 bg-status-crit/10 text-status-crit"
            : snap.runtime.state === "DEGRADED"
              ? "border-status-warn/30 bg-status-warn/5 text-status-warn"
              : "border-panel-border bg-background text-muted-foreground"
        }`}
      >
        {snap.runtime.state !== "READY" && (
          <div data-operational-banner className="flex min-w-0 flex-1 items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 truncate">
              <span className="font-semibold uppercase tracking-wider">{snap.runtime.state}</span> —{" "}
              {snap.runtime.stateReason}
              {healthReasons.length > 0 ? ` (${healthReasons.join(", ")})` : ""}
            </span>
            <span className="ml-auto shrink-0 text-[10.5px] text-muted-foreground">
              sejak {changedAt ? relativeTime(changedAt, now.toISOString()) : "—"}
            </span>
          </div>
        )}
      </div>
    </header>
  );
}

function ScenarioSwitcher({ scenario }: { scenario: ScenarioKey }) {
  return (
    <label className="flex items-center gap-1.5 rounded-md border border-panel-border bg-panel-elevated px-2 py-1 text-[11px]">
      <span className="hidden sm:inline text-muted-foreground">Fixture</span>
      <select
        value={scenario}
        onChange={(e) => getRuntimeAdapter().setScenario(e.target.value as ScenarioKey)}
        className="max-w-[110px] bg-transparent text-foreground outline-none"
        aria-label="Development fixture scenario"
      >
        {SCENARIOS.map((s) => (
          <option key={s.key} value={s.key} className="bg-background text-foreground">
            {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}
