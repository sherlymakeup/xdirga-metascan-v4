// Broker environment surfacing — reusable badges, notices, and impact panels.
// Every page that mentions broker, runtime, or execution should compose these,
// never re-derive the labels or tones locally.

import type { ReactNode } from "react";
import { AlertTriangle, FlaskConical, Info, ShieldAlert } from "lucide-react";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import {
  useBrokerEnvironment,
  type BrokerConnectionState,
  type LocalRuntimeConnectionState,
} from "@/lib/runtime/broker-environment";
import type { BrokerEnvironment, FrontendDataSource } from "@/lib/runtime/runtime-types";
import { cn } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Primitive badges
// -----------------------------------------------------------------------------

export function DataSourceBadge({ source }: { source?: FrontendDataSource }) {
  const vm = useBrokerEnvironment();
  const s = source ?? vm.frontendDataSource;
  const isFixture = s === "DEVELOPMENT_FIXTURE";
  return (
    <StatusBadge tone={isFixture ? "warn" : "info"} size="sm" dot={false}>
      {isFixture ? "Development Fixture" : "Local Runtime"}
    </StatusBadge>
  );
}

export function LocalRuntimeConnectionBadge({
  state,
}: {
  state?: LocalRuntimeConnectionState;
}) {
  const vm = useBrokerEnvironment();
  const s = state ?? vm.localRuntimeConnection;
  const tone: StatusTone =
    s === "CONNECTED"
      ? "ok"
      : s === "CONNECTING" || s === "RECONNECTING"
        ? "warn"
        : s === "STALE"
          ? "warn"
          : "crit";
  const label =
    s === "NOT_CONNECTED"
      ? "Not Connected"
      : s.charAt(0) + s.slice(1).toLowerCase().replace("_", " ");
  return (
    <StatusBadge tone={tone} size="sm" dot={false}>
      Runtime {label}
    </StatusBadge>
  );
}

export function BrokerTargetBadge() {
  return (
    <StatusBadge tone="info" size="sm" dot={false}>
      Target Exness
    </StatusBadge>
  );
}

export function BrokerEnvironmentBadge({ env }: { env?: BrokerEnvironment }) {
  const vm = useBrokerEnvironment();
  const e = env ?? vm.target.environment;
  return (
    <StatusBadge tone={e === "LIVE" ? "crit" : "warn"} size="sm" dot={false}>
      {e === "TRIAL" ? "TRIAL" : "LIVE"}
    </StatusBadge>
  );
}

export function ExecutionSemanticsBadge() {
  return (
    <StatusBadge tone="crit" size="sm" dot={false}>
      Live-Grade
    </StatusBadge>
  );
}

export function BrokerConnectionBadge({ state }: { state?: BrokerConnectionState }) {
  const vm = useBrokerEnvironment();
  const s = state ?? vm.broker.state;
  const tone: StatusTone =
    s === "CONNECTED"
      ? "ok"
      : s === "CONNECTING" || s === "RECONNECTING" || s === "DEGRADED"
        ? "warn"
        : s === "UNKNOWN"
          ? "neutral"
          : "crit";
  const suffix = vm.isFixtureDerived ? " · fixture" : "";
  return (
    <StatusBadge tone={tone} size="sm" dot={false}>
      Broker {s}
      {suffix}
    </StatusBadge>
  );
}

// -----------------------------------------------------------------------------
// Composite: horizontal environment summary (page header strip)
// -----------------------------------------------------------------------------

export function BrokerEnvironmentSummary({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5",
        compact ? "text-[10px]" : "text-[11px]",
        className,
      )}
      aria-label="Broker and runtime environment"
    >
      <DataSourceBadge />
      <LocalRuntimeConnectionBadge />
      <BrokerTargetBadge />
      <BrokerEnvironmentBadge />
      <BrokerConnectionBadge />
      <ExecutionSemanticsBadge />
    </div>
  );
}

// -----------------------------------------------------------------------------
// Authority notices — non-decorative, screen-reader accessible
// -----------------------------------------------------------------------------

export function FixtureSourceNotice({
  entity,
  className,
}: {
  entity: "order" | "position" | "action" | "data";
  className?: string;
}) {
  const vm = useBrokerEnvironment();
  if (!vm.isFixtureDerived) return null;
  const map = {
    order: {
      title: "Development Fixture Order",
      body: "No real broker order exists. Fixture rows are non-authoritative.",
    },
    position: {
      title: "Development Fixture Position",
      body: "No real broker position exists. Fixture rows are non-authoritative.",
    },
    action: {
      title: "Development Fixture Action",
      body: "No real broker request will be sent. Simulation only.",
    },
    data: {
      title: "Development Fixture Data",
      body: "Values are fixture-derived — not authoritative broker/runtime state.",
    },
  }[entity];
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2 rounded-sm border border-status-warn/40 bg-status-warn/10 px-2.5 py-1.5 text-[11px] text-status-warn",
        className,
      )}
    >
      <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="min-w-0">
        <div className="font-semibold uppercase tracking-wider">{map.title}</div>
        <div className="text-status-warn/85">{map.body}</div>
      </div>
    </div>
  );
}

export function BrokerAuthorityNotice({ className }: { className?: string }) {
  const vm = useBrokerEnvironment();
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2 rounded-sm border border-panel-border bg-panel-elevated px-2.5 py-1.5 text-[11px] text-muted-foreground",
        className,
      )}
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="min-w-0">
        <div className="font-semibold uppercase tracking-wider text-foreground/90">
          {vm.isFixtureDerived ? "Non-authoritative fixture source" : "Local runtime source"}
        </div>
        <div>
          Target {vm.providerLabel} {vm.environmentLabel} · Execution {vm.executionSemanticsLabel}.
          {vm.isFixtureDerived
            ? " Fixture-derived data does not prove that Exness, MT5, or the local runtime is connected."
            : " Values reflect the local runtime's observed state."}
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Environment impact panel — injected into every command confirmation dialog
// -----------------------------------------------------------------------------

export function EnvironmentImpactPanel({ extra }: { extra?: ReactNode }) {
  const vm = useBrokerEnvironment();
  return (
    <div className="space-y-2 text-[11.5px]">
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        <Row label="Product" value="XDIRGA METASCAN" />
        <Row label="Runtime" value="XDirga Runtime V4" />
        <Row label="Target broker" value={`${vm.providerLabel} ${vm.environmentLabel}`} />
        <Row label="Execution" value={vm.executionSemanticsLabel} tone="crit" />
        <Row
          label="Data source"
          value={vm.isFixtureDerived ? "DEVELOPMENT FIXTURE" : "LOCAL RUNTIME"}
          tone={vm.isFixtureDerived ? "warn" : "info"}
        />
        <Row
          label="Local runtime"
          value={vm.localRuntimeConnection.replace("_", " ")}
          tone={vm.localRuntimeConnection === "CONNECTED" ? "ok" : "crit"}
        />
        <Row
          label="Broker connection"
          value={vm.broker.state + (vm.isFixtureDerived ? " · fixture" : "")}
          tone={vm.broker.state === "CONNECTED" ? "ok" : "warn"}
        />
        <Row label="Data freshness" value={vm.dataFreshness ?? "UNKNOWN"} />
      </div>

      {vm.isFixtureDerived && (
        <div className="flex items-start gap-2 rounded-sm border border-status-warn/40 bg-status-warn/10 px-2 py-1.5 text-status-warn">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <div>
            <div className="font-semibold uppercase tracking-wider">
              Development Fixture Action
            </div>
            <div>No real broker request will be sent. This is a fixture simulation only.</div>
          </div>
        </div>
      )}

      {!vm.isFixtureDerived && vm.target.environment === "TRIAL" && (
        <div className="flex items-start gap-2 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1.5">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-status-warn" aria-hidden />
          <div className="text-muted-foreground">
            Target account is <span className="font-semibold text-foreground">Exness Trial</span>{" "}
            but execution semantics remain <span className="font-semibold text-status-crit">Live-Grade</span>.
            Safety confirmations are not relaxed.
          </div>
        </div>
      )}

      {extra}
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: StatusTone }) {
  return (
    <>
      <div className="text-muted-foreground">{label}</div>
      <div className="text-right">
        {tone ? (
          <StatusBadge tone={tone} size="sm" dot={false}>
            {value}
          </StatusBadge>
        ) : (
          <span className="num">{value}</span>
        )}
      </div>
    </>
  );
}
