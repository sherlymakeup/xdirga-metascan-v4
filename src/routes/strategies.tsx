import { createFileRoute } from "@tanstack/react-router";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { CommandButton } from "@/components/commands/CommandButton";
import { fmtMoney, fmtPct, relativeTime } from "@/lib/format";
import type { Strategy, StrategyStatus } from "@/lib/types";

export const Route = createFileRoute("/strategies")({
  head: () => ({
    meta: [
      { title: "Strategies · XDIRGA METASCAN" },
      { name: "description", content: "Strategy management and signal inspection." },
    ],
  }),
  component: StrategiesPage,
});

const statusTone: Record<StrategyStatus, StatusTone> = {
  DISABLED: "neutral",
  IDLE: "neutral",
  WARMING_UP: "info",
  ACTIVE: "ok",
  PAUSED: "warn",
  BLOCKED: "crit",
  DEGRADED: "warn",
  ERROR: "crit",
};

function StrategiesPage() {
  const snap = useSnapshot();
  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <Panel title="Strategies" subtitle={`${snap.strategies.length} configured`} bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left">Name</th>
                <th className="px-2 py-1.5 text-left">Symbols</th>
                <th className="px-2 py-1.5 text-left">TF</th>
                <th className="px-2 py-1.5 text-left">Status</th>
                <th className="px-2 py-1.5 text-left">Mode</th>
                <th className="px-2 py-1.5 text-right">Alloc</th>
                <th className="px-2 py-1.5 text-right">PnL Today</th>
                <th className="px-2 py-1.5 text-right">DD</th>
                <th className="px-2 py-1.5 text-right">Signals</th>
                <th className="px-2 py-1.5 text-left">Last Signal</th>
                <th className="px-2 py-1.5 text-left">Health</th>
                <th className="px-2 py-1.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {snap.strategies.map((s) => (
                <StrategyRow key={s.id} s={s} />
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Signal Inspector" subtitle="Latest strategy signal">
          <SignalCard />
        </Panel>
        <Panel title="Decision Trace" subtitle="Last decision pipeline">
          <DecisionTrace />
        </Panel>
      </div>
    </div>
  );
}

function StrategyRow({ s }: { s: Strategy }) {
  const isPaused = s.status === "PAUSED";
  const isActive = s.status === "ACTIVE" || s.status === "DEGRADED" || s.status === "WARMING_UP";
  return (
    <tr className="border-b border-panel-border/60 hover:bg-muted/40">
      <td className="px-3 py-1.5">
        <div className="font-medium">{s.name}</div>
        <div className="num text-[10px] text-muted-foreground">
          {s.id} · v{s.version}
        </div>
      </td>
      <td className="num px-2 py-1.5">{s.symbols.join(", ")}</td>
      <td className="num px-2 py-1.5">{s.timeframe}</td>
      <td className="px-2 py-1.5">
        <StatusBadge tone={statusTone[s.status]} size="sm">{s.status}</StatusBadge>
      </td>
      <td className="px-2 py-1.5">
        <StatusBadge tone={s.tradingMode === "LIVE" ? "crit" : "info"} size="sm">
          {s.tradingMode}
        </StatusBadge>
      </td>
      <td className="num px-2 py-1.5 text-right">{s.allocationPct}%</td>
      <td className={`num px-2 py-1.5 text-right ${s.pnlToday >= 0 ? "text-profit" : "text-loss"}`}>
        {fmtMoney(s.pnlToday)}
      </td>
      <td className="num px-2 py-1.5 text-right text-loss">{fmtPct(s.drawdown)}</td>
      <td className="num px-2 py-1.5 text-right">{s.signalsToday}</td>
      <td className="num px-2 py-1.5 text-muted-foreground">
        {s.lastSignalAt ? relativeTime(s.lastSignalAt) : "—"}
      </td>
      <td className="px-2 py-1.5">
        <StatusBadge tone={s.health === "OK" ? "ok" : s.health === "DEGRADED" ? "warn" : "crit"} size="sm">
          {s.health}
        </StatusBadge>
      </td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap justify-end gap-1">
          {isPaused ? (
            <CommandButton
              kind="strategy.resume"
              targetId={s.id}
              label="Resume"
              variant="outline"
              title={`Resume strategy ${s.name}`}
              description="Strategy will re-arm signals and may open new positions."
            />
          ) : (
            <CommandButton
              kind="strategy.pause"
              targetId={s.id}
              label="Pause"
              variant="outline"
              title={`Pause strategy ${s.name}`}
              description="No new signals will be acted on. Open positions remain managed."
            />
          )}
          <CommandButton
            kind="strategy.disable"
            targetId={s.id}
            label="Disable"
            variant="danger"
            confirmPhrase="DISABLE"
            title={`Disable strategy ${s.name}`}
            description="Strategy is removed from the runtime rotation until re-enabled."
            impactSummary={
              <ul className="space-y-0.5">
                <li>Allocation freed: <span className="num">{s.allocationPct}%</span></li>
                <li>Open positions are NOT auto-closed.</li>
              </ul>
            }
          />
        </div>
      </td>
    </tr>
  );
}


function SignalCard() {
  const rows: Array<[string, string, StatusTone?]> = [
    ["Symbol", "EURUSD"],
    ["Direction", "LONG", "ok"],
    ["Strength", "0.74"],
    ["Confidence", "72%"],
    ["Regime", "Trending"],
    ["Filters", "3/3 passed", "ok"],
    ["Risk approved", "yes", "ok"],
    ["Executed", "yes", "ok"],
  ];
  return (
    <dl className="grid grid-cols-2 gap-y-1 text-[11.5px]">
      {rows.map(([k, v, tone]) => (
        <div key={k} className="flex justify-between border-b border-panel-border/50 py-1">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="num">
            {tone ? <StatusBadge tone={tone} size="sm">{v}</StatusBadge> : v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function DecisionTrace() {
  const steps: Array<[string, string, StatusTone]> = [
    ["Market data received", "1.08421 @ 320ms lag", "ok"],
    ["Indicators calculated", "8 features", "ok"],
    ["Signal generated", "LONG · 0.74", "ok"],
    ["Filters evaluated", "3/3 pass", "ok"],
    ["Risk evaluated", "0.6% within 2% budget", "ok"],
    ["Safety evaluated", "All breakers CLOSED", "ok"],
    ["Execution requested", "MARKET BUY 0.5", "info"],
    ["Broker response", "Filled @ 1.08420 (41ms)", "ok"],
    ["Reconciled", "matched broker record", "ok"],
  ];
  return (
    <ol className="space-y-1.5">
      {steps.map(([label, detail, tone], i) => (
        <li key={label} className="flex items-start gap-2 text-[11.5px]">
          <span className="num mt-0.5 w-4 shrink-0 text-right text-muted-foreground">{i + 1}</span>
          <StatusBadge tone={tone} size="sm">✓</StatusBadge>
          <div className="min-w-0 flex-1">
            <div className="font-medium">{label}</div>
            <div className="num text-[11px] text-muted-foreground">{detail}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
