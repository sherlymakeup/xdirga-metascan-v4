import { createFileRoute } from "@tanstack/react-router";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { EmptyState } from "@/components/cockpit/states";
import { CommandButton } from "@/components/commands/CommandButton";
import { BrokerEnvironmentSummary, FixtureSourceNotice } from "@/components/runtime/environment-badges";
import { fmtMoney, fmtNum, fmtPct, fmtPrice, relativeTime } from "@/lib/format";
import type { Position, PositionProtection } from "@/lib/types";

export const Route = createFileRoute("/positions")({
  head: () => ({
    meta: [
      { title: "Positions · XDIRGA METASCAN" },
      { name: "description", content: "Open positions with protection status and management." },
    ],
  }),
  component: PositionsPage,
});

const protTone = (p: PositionProtection): StatusTone => {
  if (p === "PROTECTED") return "ok";
  if (p === "PARTIALLY_PROTECTED") return "warn";
  if (p === "UNPROTECTED" || p === "INVALID_PROTECTION") return "crit";
  return "neutral";
};

function PositionsPage() {
  const snap = useSnapshot();

  const totalFloat = snap.positions.reduce((s, p) => s + p.floatingPnl, 0);
  const unprotected = snap.positions.filter((p) => p.protection !== "PROTECTED").length;

  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <BrokerEnvironmentSummary />
      <FixtureSourceNotice entity="position" />
      <div className="grid gap-3 md:grid-cols-4">
        <SummaryTile label="Open positions" value={String(snap.positions.length)} />
        <SummaryTile
          label="Floating PnL"
          value={fmtMoney(totalFloat)}
          tone={totalFloat >= 0 ? "ok" : "crit"}
        />
        <SummaryTile
          label="Unprotected"
          value={String(unprotected)}
          tone={unprotected > 0 ? "warn" : "ok"}
        />
        <SummaryTile
          label="Gross exposure"
          value={fmtMoney(snap.account.grossExposure)}
        />
      </div>

      <Panel
        title="Positions"
        subtitle={`${snap.positions.length} open`}
        toolbar={
          <CommandButton
            kind="position.closeAll"
            label="Close all"
            variant="danger"
            title="Close all positions"
            description="Send market-close for every open position. Broker fills are not guaranteed."
            impactSummary={
              <ul className="space-y-0.5">
                <li>Positions: <span className="num">{snap.positions.length}</span></li>
                <li>Combined floating PnL: <span className="num">{fmtMoney(totalFloat)}</span></li>
              </ul>
            }
          />
        }
        bodyClassName="p-0"
      >
        {snap.positions.length === 0 ? (
          <EmptyState title="No open positions" description="The runtime is flat right now." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">Ticket</th>
                  <th className="px-2 py-1.5 text-left">Symbol</th>
                  <th className="px-2 py-1.5 text-left">Side</th>
                  <th className="px-2 py-1.5 text-right">Vol</th>
                  <th className="px-2 py-1.5 text-right">Entry</th>
                  <th className="px-2 py-1.5 text-right">Current</th>
                  <th className="px-2 py-1.5 text-right">SL</th>
                  <th className="px-2 py-1.5 text-right">TP</th>
                  <th className="px-2 py-1.5 text-left">Protection</th>
                  <th className="px-2 py-1.5 text-left">Autopilot</th>
                  <th className="px-2 py-1.5 text-right">Risk</th>
                  <th className="px-2 py-1.5 text-right">Float PnL</th>
                  <th className="px-2 py-1.5 text-right">Net PnL</th>
                  <th className="px-2 py-1.5 text-right">R</th>
                  <th className="px-2 py-1.5 text-left">Strategy</th>
                  <th className="px-2 py-1.5 text-left">Age</th>
                  <th className="px-2 py-1.5"></th>
                </tr>
              </thead>
              <tbody>
                {snap.positions.map((p) => (
                  <PositionRow key={p.id} p={p} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function PositionRow({ p }: { p: Position }) {
  return (
    <tr className="border-b border-panel-border/60 hover:bg-muted/40">
      <td className="num px-2 py-1.5 text-muted-foreground">{p.brokerTicket}</td>
      <td className="num px-2 py-1.5 font-semibold">{p.symbol}</td>
      <td className="px-2 py-1.5">
        <StatusBadge tone={p.side === "BUY" ? "ok" : "crit"} size="sm">
          {p.side}
        </StatusBadge>
      </td>
      <td className="num px-2 py-1.5 text-right">{fmtNum(p.volume, 2)}</td>
      <td className="num px-2 py-1.5 text-right">{fmtPrice(p.entryPrice)}</td>
      <td className="num px-2 py-1.5 text-right">{fmtPrice(p.currentPrice)}</td>
      <td className="num px-2 py-1.5 text-right">{fmtPrice(p.stopLoss)}</td>
      <td className="num px-2 py-1.5 text-right">{fmtPrice(p.takeProfit)}</td>
      <td className="px-2 py-1.5">
        <StatusBadge tone={protTone(p.protection)} size="sm">
          {p.protection.replace("_", " ")}
        </StatusBadge>
      </td>
      <td className="px-2 py-1.5">
        <AutopilotCell p={p} />
      </td>
      <td className="num px-2 py-1.5 text-right">
        {p.riskAmount == null ? "—" : fmtMoney(p.riskAmount)} <span className="text-muted-foreground">({fmtPct(p.riskPct)})</span>
      </td>
      <td className={`num px-2 py-1.5 text-right ${p.floatingPnl >= 0 ? "text-profit" : "text-loss"}`}>
        {fmtMoney(p.floatingPnl)}
      </td>
      <td className={`num px-2 py-1.5 text-right font-semibold ${p.netPnl >= 0 ? "text-profit" : "text-loss"}`}>
        {fmtMoney(p.netPnl)}
      </td>
      <td className="num px-2 py-1.5 text-right">{fmtNum(p.rMultiple, 2)}R</td>
      <td className="px-2 py-1.5 text-muted-foreground">{p.strategy}</td>
      <td className="num px-2 py-1.5 text-muted-foreground">{p.openedAt ? relativeTime(p.openedAt) : "—"}</td>
      <td className="px-2 py-1.5 text-right">
        <div className="flex justify-end gap-1">
          {p.management && (
            <CommandButton
              kind={p.management.paused ? "position.management.resume" : "position.management.pause"}
              targetId={p.id}
              label={p.management.paused ? "Resume AP" : "Pause AP"}
              variant="ghost"
              size="sm"
            />
          )}
          <CommandButton
            kind="position.close"
            targetId={p.id}
            label="Close"
            variant="outline"
            confirmPhrase="CLOSE"
            title={`Close position ${p.brokerTicket}`}
            description={`Close ${p.side} ${fmtNum(p.volume, 2)} ${p.symbol} at market.`}
            impactSummary={
              <ul className="space-y-0.5">
                <li>Current floating PnL: <span className="num">{fmtMoney(p.floatingPnl)}</span></li>
                <li>Commission + swap on record: <span className="num">{fmtMoney(p.commission + p.swap)}</span></li>
                <li>Est. net on close: <span className="num">{fmtMoney(p.netPnl)}</span></li>
                <li>Strategy allocation freed: <span className="num">{fmtPct(p.riskPct)}</span></li>
              </ul>
            }
          />
        </div>
      </td>
    </tr>
  );
}

function AutopilotCell({ p }: { p: Position }) {
  const m = p.management;
  if (!m) return <span className="text-[10px] uppercase tracking-wider text-muted-foreground">manual</span>;
  const tone: StatusTone = m.paused ? "warn" : m.lastError ? "crit" : "ok";
  const label = m.paused ? "AP PAUSED" : m.trailing.active ? "TRAILING" : m.breakEven.state === "APPLIED" ? "BE ARMED" : "AP ACTIVE";
  return (
    <div className="flex flex-col gap-0.5">
      <StatusBadge tone={tone} size="sm">{label}</StatusBadge>
      {m.nextAction && (
        <span className="line-clamp-1 max-w-[220px] text-[10px] text-muted-foreground" title={m.nextAction}>
          {m.nextAction}
        </span>
      )}
    </div>
  );
}

function SummaryTile({ label, value, tone }: { label: string; value: string; tone?: StatusTone }) {
  const color = tone === "ok" ? "text-profit" : tone === "crit" ? "text-loss" : tone === "warn" ? "text-status-warn" : "text-foreground";
  return (
    <div className="panel p-3">
      <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`num mt-1 text-lg font-semibold ${color}`}>{value}</div>
    </div>
  );
}
