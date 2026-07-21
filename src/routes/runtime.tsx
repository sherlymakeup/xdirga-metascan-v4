import { createFileRoute } from "@tanstack/react-router";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { RuntimeStateBadge } from "@/components/cockpit/runtime-state-badge";
import { CommandButton } from "@/components/commands/CommandButton";
import {
  BrokerAuthorityNotice,
  BrokerEnvironmentSummary,
} from "@/components/runtime/environment-badges";
import { fmtDuration, relativeTime } from "@/lib/format";
import type { ReconciliationSummary, Severity } from "@/lib/types";

export const Route = createFileRoute("/runtime")({
  head: () => ({
    meta: [
      { title: "Runtime · XDIRGA METASCAN" },
      { name: "description", content: "Runtime operations console and reconciliation center." },
    ],
  }),
  component: RuntimePage,
});

const sevTone = (s: Severity): StatusTone =>
  s === "CRITICAL" || s === "HIGH"
    ? "crit"
    : s === "MEDIUM"
      ? "warn"
      : s === "LOW"
        ? "info"
        : "neutral";

function RuntimePage() {
  const snap = useSnapshot();

  return (
    <>
      <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
        <BrokerEnvironmentSummary />
        <BrokerAuthorityNotice />
        <div className="grid gap-3 lg:grid-cols-3">
          <Panel title="Runtime state" className="lg:col-span-2">
            <div className="grid gap-3 md:grid-cols-2">
              <KV label="State" value={<RuntimeStateBadge state={snap.runtime.state} />} />
              <KV label="Previous" value={snap.runtime.previousState} />
              <KV label="Reason" value={snap.runtime.stateReason} full />
              <KV label="Session" value={<span className="num">{snap.runtime.sessionId}</span>} />
              <KV
                label="Uptime"
                value={snap.runtime.uptimeSec == null ? "—" : fmtDuration(snap.runtime.uptimeSec)}
              />
              <KV
                label="Version"
                value={
                  <span className="num">
                    {snap.runtime.version} · {snap.runtime.buildHash}
                  </span>
                }
              />
              <KV label="Host" value={<span className="num">{snap.runtime.hostname ?? "—"}</span>} />
              <KV
                label="Heartbeat"
                value={
                  <span className="num">
                    {snap.runtime.heartbeatLatencyMs == null
                      ? "—"
                      : `${snap.runtime.heartbeatLatencyMs}ms`}{" "}
                    ·{" "}
                    {snap.runtime.lastHeartbeatAt
                      ? relativeTime(snap.runtime.lastHeartbeatAt)
                      : "—"}
                  </span>
                }
              />
            </div>
          </Panel>

          <Panel title="Operations" subtitle="Capability-gated">
            <div className="space-y-1.5">
              <CommandButton
                kind="runtime.start"
                label="Start runtime"
                fullWidth
                variant="primary"
              />
              <CommandButton kind="runtime.pause" label="Pause" fullWidth />
              <CommandButton kind="runtime.resume" label="Resume" fullWidth />
              <CommandButton kind="runtime.restart" label="Restart" fullWidth />
              <CommandButton kind="runtime.stop" label="Stop" fullWidth variant="danger" />
              <div className="my-1 border-t border-panel-border" />
              <CommandButton kind="runtime.reconnectBroker" label="Reconnect broker" fullWidth />
              <CommandButton kind="runtime.reconcile" label="Run reconciliation" fullWidth />
              <div className="my-1 border-t border-panel-border" />
              <CommandButton
                kind={
                  snap.runtime.entriesEnabled ? "runtime.disableEntries" : "runtime.enableEntries"
                }
                label={snap.runtime.entriesEnabled ? "Disable new entries" : "Enable new entries"}
                fullWidth
                variant="outline"
              />
            </div>
          </Panel>
        </div>

        <ReconciliationPanel r={snap.reconciliation} />

        <Panel title="Subsystems" bodyClassName="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-[11.5px]">
              <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left">Subsystem</th>
                  <th className="px-2 py-1.5 text-left">State</th>
                  <th className="px-2 py-1.5 text-left">Heartbeat</th>
                  <th className="px-2 py-1.5 text-right">Latency</th>
                  <th className="px-2 py-1.5 text-right">Restarts</th>
                  <th className="px-2 py-1.5 text-left">Action</th>
                  <th className="px-2 py-1.5 text-left">Last error</th>
                </tr>
              </thead>
              <tbody>
                {snap.subsystems.map((s) => (
                  <tr key={s.key} className="border-b border-panel-border/60">
                    <td className="px-3 py-1.5 font-medium">{s.label}</td>
                    <td className="px-2 py-1.5">
                      <StatusBadge
                        tone={
                          s.state === "OK"
                            ? "ok"
                            : s.state === "DEGRADED"
                              ? "warn"
                              : s.state === "DOWN"
                                ? "crit"
                                : "neutral"
                        }
                        size="sm"
                      >
                        {s.state}
                      </StatusBadge>
                    </td>
                    <td className="num px-2 py-1.5 text-muted-foreground">
                      {relativeTime(s.lastHeartbeatAt)}
                    </td>
                    <td className="num px-2 py-1.5 text-right">
                      {s.latencyMs != null ? `${s.latencyMs}ms` : "—"}
                    </td>
                    <td className="num px-2 py-1.5 text-right">{s.restartCount}</td>
                    <td className="px-2 py-1.5 text-muted-foreground">{s.currentAction ?? "—"}</td>
                    <td className="px-2 py-1.5 text-status-crit/90">{s.lastError ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Recent events" subtitle="Runtime + subsystem log" bodyClassName="p-0">
          <div className="max-h-[400px] overflow-auto">
            <table className="w-full text-[11px]">
              <tbody>
                {snap.events.slice(0, 40).map((e) => (
                  <tr key={e.id} className="border-b border-panel-border/60">
                    <td className="num w-24 px-2 py-1 text-muted-foreground">
                      {relativeTime(e.at)}
                    </td>
                    <td className="w-20 px-2 py-1">
                      <StatusBadge
                        tone={
                          e.severity === "CRITICAL" || e.severity === "ERROR"
                            ? "crit"
                            : e.severity === "WARNING"
                              ? "warn"
                              : "info"
                        }
                        size="sm"
                      >
                        {e.severity}
                      </StatusBadge>
                    </td>
                    <td className="w-32 px-2 py-1 text-muted-foreground">{e.component}</td>
                    <td className="px-2 py-1">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}

function ReconciliationPanel({ r }: { r: ReconciliationSummary }) {
  const stateTone: StatusTone =
    r.state === "OK"
      ? "ok"
      : r.state === "RUNNING"
        ? "info"
        : r.state === "ISSUES"
          ? "warn"
          : r.state === "FAILED"
            ? "crit"
            : "neutral";
  return (
    <Panel
      title="Reconciliation"
      subtitle={r.lastRunAt ? `Last run ${relativeTime(r.lastRunAt)}` : "Last run —"}
      toolbar={
        <StatusBadge tone={stateTone} size="sm">
          {r.state}
        </StatusBadge>
      }
    >
      <div className="grid gap-3 md:grid-cols-4">
        <ReconTile label="Runtime orders" value={r.runtimeOrders} />
        <ReconTile
          label="Broker orders"
          value={r.brokerOrders}
          diff={r.brokerOrders - r.runtimeOrders}
        />
        <ReconTile label="Runtime positions" value={r.runtimePositions} />
        <ReconTile
          label="Broker positions"
          value={r.brokerPositions}
          diff={r.brokerPositions - r.runtimePositions}
        />
        <ReconTile label="Missing orders" value={r.missingOrders} warn={r.missingOrders > 0} />
        <ReconTile label="Unknown orders" value={r.unknownOrders} warn={r.unknownOrders > 0} />
        <ReconTile
          label="Position mismatches"
          value={r.positionMismatches}
          warn={r.positionMismatches > 0}
        />
        <ReconTile
          label="Volume mismatches"
          value={r.volumeMismatches}
          warn={r.volumeMismatches > 0}
        />
      </div>

      {r.issues.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-sm border border-panel-border">
          <table className="w-full text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Severity</th>
                <th className="px-2 py-1 text-left">Entity</th>
                <th className="px-2 py-1 text-left">Runtime</th>
                <th className="px-2 py-1 text-left">Broker</th>
                <th className="px-2 py-1 text-left">Diff</th>
                <th className="px-2 py-1 text-left">Suggested action</th>
              </tr>
            </thead>
            <tbody>
              {r.issues.map((i, idx) => (
                <tr key={idx} className="border-b border-panel-border/60">
                  <td className="px-2 py-1">
                    <StatusBadge tone={sevTone(i.severity)} size="sm">
                      {i.severity}
                    </StatusBadge>
                  </td>
                  <td className="num px-2 py-1">
                    {i.entity} {i.entityId}
                  </td>
                  <td className="num px-2 py-1">{i.runtimeState}</td>
                  <td className="num px-2 py-1">{i.brokerState}</td>
                  <td className="num px-2 py-1 text-status-warn">{i.difference}</td>
                  <td className="px-2 py-1 text-muted-foreground">{i.suggestedAction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function ReconTile({
  label,
  value,
  diff,
  warn,
}: {
  label: string;
  value: number;
  diff?: number;
  warn?: boolean;
}) {
  return (
    <div className="rounded-sm border border-panel-border bg-panel-elevated p-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div
        className={`num mt-0.5 text-lg font-semibold ${warn ? "text-status-warn" : "text-foreground"}`}
      >
        {value}
      </div>
      {diff != null && diff !== 0 && (
        <div className={`num text-[10.5px] ${diff > 0 ? "text-status-warn" : "text-status-crit"}`}>
          Δ {diff > 0 ? "+" : ""}
          {diff}
        </div>
      )}
    </div>
  );
}

function KV({ label, value, full }: { label: string; value: React.ReactNode; full?: boolean }) {
  return (
    <div
      className={`flex items-baseline justify-between gap-2 border-b border-panel-border/50 py-1 text-[11.5px] ${full ? "md:col-span-2" : ""}`}
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
