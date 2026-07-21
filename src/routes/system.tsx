import { createFileRoute } from "@tanstack/react-router";
import { useScenario } from "@/lib/adapters/runtime";
import {
  getRuntimeAdapter,
  useConvergence,
  useHandshake,
  useHandshakeCompatibility,
  useSnapshotHydration,
} from "@/lib/runtime";
import { DEVELOPMENT_FEATURES_ENABLED } from "@/lib/runtime/dev-flags";

import { Panel } from "@/components/cockpit/panel";
import { StatusBadge } from "@/components/cockpit/status-badge";
import { FixtureDiagnosticsPanel } from "@/components/runtime/GlobalOperationalStateBanner";
import type { ScenarioKey } from "@/lib/types";
import { SCENARIOS } from "@/lib/demo/scenarios";

export const Route = createFileRoute("/system")({
  head: () => ({
    meta: [
      { title: "System · XDIRGA METASCAN" },
      { name: "description", content: "System diagnostics, data source, and development fixtures." },
    ],
  }),
  component: SystemPage,
});

function SystemPage() {
  const current = useScenario();
  const adapter = getRuntimeAdapter();
  const dataSource: "DEVELOPMENT_FIXTURE" | "LOCAL_RUNTIME" =
    adapter.adapterType === "fixture" ? "DEVELOPMENT_FIXTURE" : "LOCAL_RUNTIME";
  const isFixture = adapter.adapterType === "fixture";

  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <Panel
        title="System identity"
        subtitle="Truthful snapshot of what this frontend is currently bound to"
      >
        <dl className="grid gap-x-6 gap-y-2 text-[12px] md:grid-cols-2">
          <Row label="Product" value="XDIRGA METASCAN" />
          <Row label="Runtime Engine" value="XDirga Runtime V4" />
          <Row
            label="Frontend Data Source"
            value={isFixture ? "DEVELOPMENT_FIXTURE" : "LOCAL_RUNTIME"}
            tone={isFixture ? "warn" : "ok"}
          />
          <Row
            label="Local Runtime Connection"
            value={isFixture ? "NOT CONNECTED" : "SEE CONNECTION BANNER"}
            tone={isFixture ? "crit" : "info"}
          />
          <Row label="Target Broker" value="Exness" />
          <Row label="Target Environment" value="TRIAL" tone="warn" />
          <Row label="Execution Semantics" value="LIVE" tone="crit" />
          <Row label="Adapter" value={`${adapter.adapterType} · ${dataSource}`} />
        </dl>
        <p className="mt-3 text-[11.5px] text-muted-foreground">
          The frontend never claims that Exness, MetaTrader 5, or a local runtime is connected
          unless the backend reports so. When a local runtime becomes available and drops, the UI
          shows <span className="font-semibold">DISCONNECTED</span> — it does not silently fall
          back to fixture data.
        </p>
      </Panel>

      <HandshakePanel />

      <ConvergencePanel />

      {DEVELOPMENT_FEATURES_ENABLED && (
        <Panel title="Operational diagnostics" subtitle="Live view of the state resolver — development only.">
          <FixtureDiagnosticsPanel />
        </Panel>
      )}




      {isFixture && DEVELOPMENT_FEATURES_ENABLED && (
        <Panel
          title="Development fixtures"
          subtitle="Developer-only. Switch the fixture into different operational states for UI review."
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[10.5px] uppercase tracking-widest">
            <StatusBadge tone="warn">DEVELOPMENT FIXTURE ACTIVE</StatusBadge>
            <StatusBadge tone="crit">NO LOCAL RUNTIME CONNECTED</StatusBadge>
            <StatusBadge tone="info">TARGET: EXNESS TRIAL</StatusBadge>
            <StatusBadge tone="crit">LIVE-GRADE SAFETY</StatusBadge>
          </div>
          <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
            {SCENARIOS.map((s) => (
              <button
                key={s.key}
                onClick={() => getRuntimeAdapter().setScenario?.(s.key as ScenarioKey)}
                className={`rounded-sm border p-3 text-left transition-colors ${
                  current === s.key
                    ? "border-primary bg-primary/10"
                    : "border-panel-border bg-panel-elevated hover:bg-muted"
                }`}
              >
                <div className="text-[12.5px] font-semibold">{s.label}</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">{s.description}</div>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="About">
        <p className="text-[12px] text-muted-foreground">
          XDIRGA METASCAN is a local-first automated trading control plane. This frontend
          renders runtime state truthfully — including uncertainty and degraded modes — and only
          ever <em>requests</em> actions from the runtime; execution is authoritative on the
          backend. There is intentionally no operator-facing selector for DEMO, PAPER, or REPLAY:
          fixtures are a development data source, not a trading mode.
        </p>
      </Panel>
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "crit" | "info";
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-panel-border/60 py-1.5">
      <dt className="text-[11px] uppercase tracking-widest text-muted-foreground">{label}</dt>
      <dd className="num text-[12.5px] font-semibold">
        {tone ? <StatusBadge tone={tone} size="sm">{value}</StatusBadge> : value}
      </dd>
    </div>
  );
}

function HandshakePanel() {
  const handshake = useHandshake();
  const compat = useHandshakeCompatibility();
  const adapter = getRuntimeAdapter();
  const isFixture = adapter.adapterType === "fixture";
  const current = isFixture ? (adapter.getHandshakeMismatch?.() ?? "none") : "none";

  const severityTone =
    compat.severity === "OK" ? "ok" : compat.severity === "WARN" ? "warn" : "crit";

  return (
    <Panel
      title="Runtime handshake"
      subtitle="Protocol / schema negotiation between the frontend and the local runtime"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[10.5px] uppercase tracking-widest">
        <StatusBadge tone={severityTone}>{compat.severity}</StatusBadge>
        {compat.safeMode && <StatusBadge tone="crit">SAFE MODE ENGAGED</StatusBadge>}
        <StatusBadge tone="info">{compat.reasons.length} findings</StatusBadge>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-sm border border-panel-border bg-panel-elevated p-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Frontend expects
          </div>
          <dl className="num mt-2 space-y-1 text-[12px]">
            <Row label="Protocol" value={`${compat.expected.protocolId} ${compat.expected.protocolVersion}`} />
            <Row label="Schema" value={compat.expected.schemaVersion} />
            <Row label="Schema hash" value={compat.expected.schemaHash} />
            <Row label="Min runtime" value={compat.expected.minRuntimeVersion} />
            <Row label="Required features" value={String(compat.expected.requiredFeatures.length)} />
            <Row label="Required commands" value={String(compat.expected.requiredCommands.length)} />
          </dl>
        </div>

        <div className="rounded-sm border border-panel-border bg-panel-elevated p-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Runtime reports
          </div>
          {handshake ? (
            <dl className="num mt-2 space-y-1 text-[12px]">
              <Row label="Runtime" value={`${handshake.runtimeName} ${handshake.runtimeVersion}`} />
              <Row label="Protocol" value={`${handshake.protocolId} ${handshake.protocolVersion}`} />
              <Row label="Schema" value={handshake.schemaVersion} />
              <Row label="Schema hash" value={handshake.schemaHash} />
              <Row label="Broker env" value={handshake.brokerEnvironment ?? "—"} tone="warn" />
              <Row label="Features" value={String(handshake.supportedFeatures.length)} />
              <Row label="Commands" value={String(handshake.supportedCommands.length)} />
            </dl>
          ) : (
            <p className="mt-2 text-[11.5px] text-muted-foreground">No handshake received.</p>
          )}
        </div>
      </div>

      {compat.reasons.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Findings
          </div>
          <ul className="mt-1 space-y-1">
            {compat.reasons.map((r, i) => (
              <li
                key={`${r.code}-${i}`}
                className="flex items-start gap-2 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1.5 text-[11.5px]"
              >
                <StatusBadge tone={r.severity === "INCOMPATIBLE" ? "crit" : "warn"} size="sm">
                  {r.severity}
                </StatusBadge>
                <div className="min-w-0">
                  <div className="num text-[10.5px] font-semibold text-muted-foreground">{r.code}</div>
                  <div>{r.message}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isFixture && DEVELOPMENT_FEATURES_ENABLED && (
        <div className="mt-4 rounded-sm border border-dashed border-panel-border p-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Dev-only · Simulate handshake mismatch
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Rewrite the fixture handshake to exercise the mismatch banner and SAFE MODE lockout.
            No effect on real runtime behavior.
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
            {(["none", "minor", "major"] as const).map((kind) => (
              <button
                key={kind}
                onClick={() => adapter.simulateHandshakeMismatch?.(kind)}
                className={`rounded-sm border px-3 py-1 uppercase tracking-widest transition-colors ${
                  current === kind
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-panel-border bg-panel-elevated hover:bg-muted"
                }`}
              >
                {kind === "none" ? "OK (match)" : kind === "minor" ? "Warn (minor drift)" : "Incompatible (major)"}
              </button>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

function ConvergencePanel() {
  const conv = useConvergence();
  const hyd = useSnapshotHydration();
  const tone =
    conv.status === "CONVERGED"
      ? "ok"
      : conv.status === "UNKNOWN"
        ? "info"
        : conv.status === "BOOT_MISMATCH"
          ? "crit"
          : "warn";
  return (
    <Panel
      title="Snapshot ↔ event convergence"
      subtitle="Live drift between the last accepted snapshot revision and the highest observed event revision"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[10.5px] uppercase tracking-widest">
        <StatusBadge tone={tone}>{conv.status}</StatusBadge>
        {conv.revisionDrift !== null && (
          <StatusBadge tone="info">
            DRIFT {conv.revisionDrift > 0 ? `+${conv.revisionDrift}` : conv.revisionDrift}
          </StatusBadge>
        )}
        <StatusBadge tone="info">
          ACCEPTED {hyd.acceptedCount} · REJECTED {hyd.rejectedCount}
        </StatusBadge>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-sm border border-panel-border bg-panel-elevated p-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Snapshot
          </div>
          <dl className="num mt-2 space-y-1 text-[12px]">
            <Row label="Boot" value={conv.snapshotBootId ?? "—"} />
            <Row label="Revision" value={String(conv.snapshotRevision ?? "—")} />
            <Row label="Sequence" value={String(conv.snapshotSequence ?? "—")} />
            <Row label="Last reason" value={hyd.lastReason ?? "—"} />
            <Row label="Hydrated at" value={hyd.hydratedAt ?? "—"} />
          </dl>
        </div>
        <div className="rounded-sm border border-panel-border bg-panel-elevated p-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Event stream
          </div>
          <dl className="num mt-2 space-y-1 text-[12px]">
            <Row label="Boot" value={conv.latestEventBootId ?? "—"} />
            <Row label="Revision" value={String(conv.latestEventRevision ?? "—")} />
            <Row label="Sequence" value={String(conv.latestEventSequence ?? "—")} />
            <Row label="Observed at" value={conv.observedAt ?? "—"} />
          </dl>
        </div>
      </div>
      <p className="mt-3 text-[11.5px] text-muted-foreground">
        A healthy runtime keeps events within a small window of the last accepted snapshot.
        <span className="font-semibold"> EVENTS_AHEAD</span> is normal briefly between snapshots;
        <span className="font-semibold"> SNAPSHOT_AHEAD</span> or
        <span className="font-semibold"> BOOT_MISMATCH</span> means the streams have diverged and
        the frontend should re-hydrate.
      </p>
    </Panel>
  );
}
