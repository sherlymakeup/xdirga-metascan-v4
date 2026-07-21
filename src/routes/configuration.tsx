import { createFileRoute } from "@tanstack/react-router";
import { CheckCheck, PlayCircle, Undo2 } from "lucide-react";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge } from "@/components/cockpit/status-badge";
import { CommandButton } from "@/components/commands/CommandButton";

export const Route = createFileRoute("/configuration")({
  head: () => ({
    meta: [
      { title: "Configuration · XDIRGA METASCAN" },
      { name: "description", content: "Runtime, broker, and strategy configuration." },
    ],
  }),
  component: ConfigPage,
});

function ConfigPage() {
  const snap = useSnapshot();
  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <Panel bodyClassName="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Configuration Console
            </div>
            <h1 className="mt-0.5 text-[15px] font-semibold leading-tight">
              Runtime configuration
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[10.5px] text-muted-foreground">
              <StatusBadge tone="info" size="sm">
                READ-ONLY VIEW
              </StatusBadge>
              <span>
                Changes are authored on the runtime host and applied via signed revisions.
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CommandButton
              kind="config.validate"
              label="Validate"
              icon={<CheckCheck className="h-3.5 w-3.5" />}
              skipConfirmation
              variant="outline"
            />
            <CommandButton
              kind="config.apply"
              label="Apply pending"
              icon={<PlayCircle className="h-3.5 w-3.5" />}
              variant="primary"
              title="Apply pending configuration revision"
              description="Applies the currently staged configuration revision to the local runtime. New strategies, symbols, and risk limits take effect immediately."
              impactSummary={
                <>
                  Runtime revision advances. Active strategies may reload state. Broker session is
                  preserved.
                </>
              }
            />
            <CommandButton
              kind="config.rollback"
              label="Rollback"
              icon={<Undo2 className="h-3.5 w-3.5" />}
              variant="danger"
              title="Rollback to previous revision"
              description="Reverts the runtime configuration to the previously applied revision."
              impactSummary={
                <>
                  Rolling back will re-load the last known-good configuration. In-flight strategy
                  state may reset.
                </>
              }
              confirmPhrase="ROLLBACK"
            />
          </div>
        </div>
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Runtime" subtitle="Read-only from the backing runtime">
          <KVList
            rows={[
              ["Environment", snap.runtime.environment],
              ["Trading mode", snap.runtime.tradingMode],
              ["Automation", snap.runtime.automationEnabled ? "ENABLED" : "DISABLED"],
              ["Entries", snap.runtime.entriesEnabled ? "OPEN" : "BLOCKED"],
              ["Hostname", snap.runtime.hostname ?? "—"],
              ["OS", snap.runtime.os ?? "—"],
              ["PID", snap.runtime.pid == null ? "—" : String(snap.runtime.pid)],
              ["Version", `${snap.runtime.version} · ${snap.runtime.buildHash}`],
            ]}
          />
        </Panel>

        <Panel title="Broker" subtitle={`${snap.broker.broker} · ${snap.broker.server}`}>
          <KVList
            rows={[
              ["Login", snap.broker.loginMasked],
              ["Account mode", snap.broker.accountMode],
              ["Connection", snap.broker.connection],
              ["Trading permitted", snap.broker.tradingPermitted ? "YES" : "NO"],
              ["Terminal", snap.broker.terminalVersion],
              ["Avg latency", `${snap.broker.avgLatencyMs}ms`],
              ["Timeouts", String(snap.broker.timeoutCount)],
              ["Reconnects", String(snap.broker.reconnectAttempts)],
            ]}
          />
        </Panel>
      </div>

      <Panel title="Symbols" subtitle={`${snap.markets.length} configured`} bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left">Symbol</th>
                <th className="px-2 py-1.5 text-left">Group</th>
                <th className="px-2 py-1.5 text-right">Contract</th>
                <th className="px-2 py-1.5 text-right">Tick</th>
                <th className="px-2 py-1.5 text-right">Vol step</th>
                <th className="px-2 py-1.5 text-right">Min / Max</th>
                <th className="px-2 py-1.5 text-right">Margin</th>
                <th className="px-2 py-1.5 text-left">Session</th>
              </tr>
            </thead>
            <tbody>
              {snap.markets.map((m) => (
                <tr key={m.symbol} className="border-b border-panel-border/60">
                  <td className="num px-3 py-1.5 font-semibold">{m.symbol}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{m.group}</td>
                  <td className="num px-2 py-1.5 text-right">{m.contractSize.toLocaleString()}</td>
                  <td className="num px-2 py-1.5 text-right">{m.tickSize}</td>
                  <td className="num px-2 py-1.5 text-right">{m.volumeStep}</td>
                  <td className="num px-2 py-1.5 text-right">
                    {m.minVolume} / {m.maxVolume}
                  </td>
                  <td className="num px-2 py-1.5 text-right">{m.marginRequirement}</td>
                  <td className="px-2 py-1.5">
                    <StatusBadge tone={m.sessionOpen ? "ok" : "neutral"} size="sm">
                      {m.sessionOpen ? "OPEN" : "CLOSED"}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function KVList({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid grid-cols-2 gap-y-1 text-[11.5px]">
      {rows.map(([k, v]) => (
        <div
          key={k}
          className="col-span-2 flex justify-between border-b border-panel-border/50 py-1"
        >
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="num text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
