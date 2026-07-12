import { createFileRoute } from "@tanstack/react-router";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { RiskMeter } from "@/components/cockpit/risk-meter";
import { CommandButton } from "@/components/commands/CommandButton";
import { BrokerAuthorityNotice, BrokerEnvironmentSummary } from "@/components/runtime/environment-badges";
import { fmtMoney, fmtNum, fmtPct, relativeTime } from "@/lib/format";
import type { BreakerState, RiskLimit } from "@/lib/types";

export const Route = createFileRoute("/risk")({
  head: () => ({
    meta: [
      { title: "Risk & Safety · XDIRGA METASCAN" },
      { name: "description", content: "Risk limits and circuit breakers control center." },
    ],
  }),
  component: RiskPage,
});

const breakerTone = (s: BreakerState): StatusTone => {
  if (s === "CLOSED") return "ok";
  if (s === "WARNING" || s === "RECOVERING") return "warn";
  if (s === "OPEN" || s === "MANUAL_LOCK") return "crit";
  return "neutral";
};

function unit(l: RiskLimit) {
  if (l.unit === "USD") return fmtMoney(l.current);
  if (l.unit === "PCT") return fmtPct(l.current);
  if (l.unit === "MS") return `${fmtNum(l.current, 0)}ms`;
  return fmtNum(l.current, 0);
}
function unitMax(l: RiskLimit) {
  if (l.unit === "USD") return fmtMoney(l.configured);
  if (l.unit === "PCT") return fmtPct(l.configured);
  if (l.unit === "MS") return `${fmtNum(l.configured, 0)}ms`;
  return fmtNum(l.configured, 0);
}

function RiskPage() {
  const snap = useSnapshot();

  const openBreakers = snap.breakers.filter((b) => b.state !== "CLOSED");

  return (
    <>
      <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <BrokerEnvironmentSummary />
      <BrokerAuthorityNotice />
        <div className="grid gap-3 lg:grid-cols-3">
          <Panel title="Risk budget" subtitle="Current utilization" className="lg:col-span-2">
            <div className="grid gap-3 md:grid-cols-2">
              {snap.riskLimits.map((l) => (
                <RiskMeter
                  key={l.key}
                  value={l.current}
                  warnAt={l.warnAt}
                  breachAt={l.breachAt}
                  label={l.label}
                  displayValue={unit(l)}
                  displayMax={unitMax(l)}
                />
              ))}
            </div>
          </Panel>

          <Panel
            title="Emergency"
            subtitle="Immediate stop of automation"
            toolbar={<StatusBadge tone={openBreakers.length > 0 ? "crit" : "ok"} size="sm">
              {openBreakers.length > 0 ? `${openBreakers.length} BREAKERS OPEN` : "ALL CLEAR"}
            </StatusBadge>}
          >
            <div className="space-y-3 text-[12px]">
              <p className="text-muted-foreground">
                Emergency kill disables entries, cancels all working orders, and requests flat.
                Broker fills are not guaranteed — treat as a stop request.
              </p>
              <CommandButton
                kind="runtime.emergencyKill"
                label="Emergency Kill"
                variant="danger"
                size="md"
                fullWidth
                impactSummary={
                  <ul className="space-y-0.5">
                    <li>Automation → DISABLED</li>
                    <li>Working orders → CANCEL requested</li>
                    <li>Open positions → MARKET CLOSE requested</li>
                    <li>Runtime state → KILLED (manual restart required)</li>
                  </ul>
                }
              />
              <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <div>Last kill</div>
                <div className="num text-right text-foreground">Never</div>
                <div>Automation</div>
                <div className="text-right">
                  <StatusBadge tone={snap.runtime.automationEnabled ? "ok" : "warn"} size="sm">
                    {snap.runtime.automationEnabled ? "ENABLED" : "DISABLED"}
                  </StatusBadge>
                </div>
                <div>Entries</div>
                <div className="text-right">
                  <StatusBadge tone={snap.runtime.entriesEnabled ? "ok" : "warn"} size="sm">
                    {snap.runtime.entriesEnabled ? "OPEN" : "BLOCKED"}
                  </StatusBadge>
                </div>
              </div>
            </div>
          </Panel>
        </div>

        <Panel title="Circuit breakers" subtitle={`${snap.breakers.length} configured`} bodyClassName="p-0">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left">Breaker</th>
                <th className="px-2 py-1.5 text-left">State</th>
                <th className="px-2 py-1.5 text-left">Trigger</th>
                <th className="px-2 py-1.5 text-left">Current</th>
                <th className="px-2 py-1.5 text-left">Threshold</th>
                <th className="px-2 py-1.5 text-left">Recovery</th>
                <th className="px-2 py-1.5 text-left">Triggered</th>
                <th className="px-2 py-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {snap.breakers.map((b) => (
                <tr key={b.key} className="border-b border-panel-border/60">
                  <td className="px-3 py-1.5 font-medium">{b.label}</td>
                  <td className="px-2 py-1.5">
                    <StatusBadge tone={breakerTone(b.state)} size="sm" pulse={b.state === "OPEN"}>
                      {b.state}
                    </StatusBadge>
                  </td>
                  <td className="px-2 py-1.5 text-muted-foreground">{b.triggerCondition}</td>
                  <td className="num px-2 py-1.5">{b.currentValue}</td>
                  <td className="num px-2 py-1.5">{b.threshold}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{b.recoveryCondition}</td>
                  <td className="num px-2 py-1.5 text-muted-foreground">
                    {b.triggeredAt ? relativeTime(b.triggeredAt) : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {b.state !== "CLOSED" && b.manualResetAllowed && (
                      <CommandButton
                        kind="breaker.reset"
                        label="Reset"
                        targetId={b.key}
                        title={`Reset breaker: ${b.label}`}
                        description="Resetting a breaker re-enables the associated safety path. Ensure the underlying condition is resolved."
                        confirmPhrase="RESET"
                        variant="outline"
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Panel>

        <Panel title="Configured limits" subtitle="Change history is preserved" bodyClassName="p-0">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left">Limit</th>
                <th className="px-2 py-1.5 text-right">Configured</th>
                <th className="px-2 py-1.5 text-right">Current</th>
                <th className="px-2 py-1.5 text-right">Warn</th>
                <th className="px-2 py-1.5 text-right">Breach</th>
                <th className="px-2 py-1.5 text-left">Changed</th>
                <th className="px-2 py-1.5 text-left">By</th>
              </tr>
            </thead>
            <tbody>
              {snap.riskLimits.map((l) => (
                <tr key={l.key} className="border-b border-panel-border/60">
                  <td className="px-3 py-1.5">{l.label}</td>
                  <td className="num px-2 py-1.5 text-right">{unitMax(l)}</td>
                  <td className={`num px-2 py-1.5 text-right ${l.breached ? "text-status-crit" : ""}`}>{unit(l)}</td>
                  <td className="num px-2 py-1.5 text-right text-status-warn">{l.warnAt}</td>
                  <td className="num px-2 py-1.5 text-right text-status-crit">{l.breachAt}</td>
                  <td className="num px-2 py-1.5 text-muted-foreground">{relativeTime(l.changedAt)}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{l.changedBy}</td>
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
