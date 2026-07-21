import { createFileRoute } from "@tanstack/react-router";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { EmptyState } from "@/components/cockpit/states";
import { fmtMoney, fmtNum, fmtPct } from "@/lib/format";
import {
  computeJournalStats,
  computeRHistogram,
  useTradeJournal,
} from "@/lib/runtime/domain/trade-journal";
import { loadMoreTradeHistory } from "@/lib/runtime/events/bootstrap";
import { useMemo } from "react";
import { StatusBadge } from "@/components/cockpit/status-badge";

export const Route = createFileRoute("/analytics")({
  head: () => ({
    meta: [
      { title: "Analytics · XDIRGA METASCAN" },
      { name: "description", content: "Performance analytics and closed-trade journal." },
    ],
  }),
  component: AnalyticsPage,
});

function AnalyticsPage() {
  const snap = useSnapshot();
  const journal = useTradeJournal();
  const stats = useMemo(() => computeJournalStats(journal.trades), [journal.trades]);
  const histogram = useMemo(() => computeRHistogram(journal.trades), [journal.trades]);
  const maxBucket = Math.max(1, ...histogram.map((h) => h.count));

  const summary = [
    ["Realised PnL (today)", fmtMoney(snap.account.realizedPnlToday)],
    ["Realised PnL (week)", fmtMoney(snap.account.realizedPnlWeek)],
    ["Win rate", fmtPct(snap.account.winRate)],
    ["Profit factor", fmtNum(snap.account.profitFactor, 2)],
    ["Trades today", String(snap.account.tradesToday)],
    ["Max drawdown", fmtPct(snap.account.maxDrawdown)],
  ];
  const curve = snap.equityCurve;
  const sparkPath = buildSparkPath(
    curve.map((p) => p.equity),
    640,
    60,
  );
  const firstEq = curve[0]?.equity ?? 0;
  const lastEq = curve[curve.length - 1]?.equity ?? 0;
  const delta = lastEq - firstEq;
  const deltaPct = firstEq ? (delta / firstEq) * 100 : 0;

  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      <Panel title="Equity curve" subtitle={`${curve.length} samples · session`}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Equity now
            </div>
            <div className="num text-2xl font-semibold">{fmtMoney(lastEq)}</div>
            <div
              className={`num mt-0.5 text-[11.5px] font-medium ${delta >= 0 ? "text-profit" : "text-loss"}`}
            >
              {delta >= 0 ? "+" : ""}
              {fmtMoney(delta)} ({fmtPct(deltaPct / 100)})
            </div>
          </div>
          <svg
            viewBox="0 0 640 60"
            className="h-14 w-full max-w-[640px]"
            preserveAspectRatio="none"
          >
            <path
              d={sparkPath}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              className={delta >= 0 ? "text-profit" : "text-loss"}
            />
          </svg>
        </div>
      </Panel>

      <Panel title="Performance summary">
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
          {summary.map(([k, v]) => (
            <div key={k} className="rounded-sm border border-panel-border bg-panel-elevated p-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
              <div className="num mt-0.5 text-base font-semibold">{v}</div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title="Journal — closed trades"
        subtitle={`${stats.total} rows · ${journal.bySource.events} live · ${journal.bySource.history} history${journal.overwrittenByEvent > 0 ? ` · ${journal.overwrittenByEvent} overwritten by event` : ""}`}
      >
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Net PnL"
            value={fmtMoney(stats.netPnl)}
            tone={stats.netPnl >= 0 ? "ok" : "crit"}
          />
          <StatTile
            label="Gross / Commission / Swap"
            value={`${fmtMoney(stats.grossPnl)} · ${fmtMoney(stats.commission)} · ${fmtMoney(stats.swap)}`}
            sub="net = gross + commission + swap"
          />
          <StatTile
            label="Win rate"
            value={fmtPct(stats.winRate)}
            sub={`${stats.wins}W / ${stats.losses}L / ${stats.scratches}=`}
          />
          <StatTile
            label="Avg R"
            value={stats.avgR === null ? "n/a" : `${fmtNum(stats.avgR, 2)}R`}
            sub={
              stats.naR > 0
                ? `${stats.rScored} scored · ${stats.naR} n/a R (excluded)`
                : `${stats.rScored} scored`
            }
            tone={
              stats.avgR !== null && stats.avgR >= 0
                ? "ok"
                : stats.avgR === null
                  ? "neutral"
                  : "crit"
            }
          />
        </div>

        <div className="mt-3 rounded-sm border border-panel-border bg-panel-elevated p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              R-multiple distribution
            </div>
            {stats.naR > 0 && (
              <StatusBadge tone="warn" size="sm">
                {stats.naR} n/a R excluded
              </StatusBadge>
            )}
          </div>
          <div className="flex items-end gap-1.5">
            {histogram.map((b) => (
              <div key={b.label} className="flex flex-1 flex-col items-center gap-1">
                <div className="flex h-24 w-full items-end">
                  <div
                    className={`w-full rounded-sm ${b.label.startsWith("-") || b.label.startsWith("≤") ? "bg-loss/70" : "bg-profit/70"}`}
                    style={{ height: `${(b.count / maxBucket) * 100}%` }}
                    title={`${b.count} trades`}
                  />
                </div>
                <div className="num text-[10px] text-muted-foreground">{b.count}</div>
                <div className="text-[9.5px] uppercase tracking-wider text-muted-foreground">
                  {b.label}
                </div>
              </div>
            ))}
          </div>
        </div>

        {stats.total === 0 ? (
          <div className="mt-3">
            <EmptyState
              title="No closed trades yet"
              description="Closed trades will appear here as the runtime emits trade.closed events."
            />
          </div>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[900px] text-[11.5px]">
              <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">Trade</th>
                  <th className="px-2 py-1.5 text-left">Symbol</th>
                  <th className="px-2 py-1.5 text-left">Dir</th>
                  <th className="px-2 py-1.5 text-right">Gross</th>
                  <th className="px-2 py-1.5 text-right">Comm</th>
                  <th className="px-2 py-1.5 text-right">Swap</th>
                  <th className="px-2 py-1.5 text-right">Net</th>
                  <th className="px-2 py-1.5 text-right">R</th>
                  <th className="px-2 py-1.5 text-left">Exit</th>
                </tr>
              </thead>
              <tbody>
                {journal.trades.slice(0, 60).map((t) => (
                  <tr key={t.tradeId} className="border-b border-panel-border/60">
                    <td className="num px-2 py-1.5 text-muted-foreground">{t.tradeId}</td>
                    <td className="num px-2 py-1.5 font-semibold">{t.symbol}</td>
                    <td className="px-2 py-1.5">
                      <StatusBadge tone={t.direction === "LONG" ? "ok" : "crit"} size="sm">
                        {t.direction}
                      </StatusBadge>
                    </td>
                    <td
                      className={`num px-2 py-1.5 text-right ${t.grossPnl >= 0 ? "text-profit" : "text-loss"}`}
                    >
                      {fmtMoney(t.grossPnl)}
                    </td>
                    <td className="num px-2 py-1.5 text-right text-muted-foreground">
                      {fmtMoney(t.commission)}
                    </td>
                    <td className="num px-2 py-1.5 text-right text-muted-foreground">
                      {fmtMoney(t.swap)}
                    </td>
                    <td
                      className={`num px-2 py-1.5 text-right font-semibold ${t.netPnl >= 0 ? "text-profit" : "text-loss"}`}
                    >
                      {fmtMoney(t.netPnl)}
                    </td>
                    <td className="num px-2 py-1.5 text-right">
                      {t.rMultiple === null ? (
                        <span className="text-muted-foreground">n/a</span>
                      ) : (
                        <span>{fmtNum(t.rMultiple, 2)}R</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">{t.exitReason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {journal.nextCursor && (
              <div className="mt-3 flex justify-center">
                <button
                  type="button"
                  onClick={() => void loadMoreTradeHistory(100)}
                  disabled={journal.loading}
                  className="rounded-sm border border-panel-border bg-panel-elevated px-3 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  {journal.loading ? "Loading…" : "Load more history"}
                </button>
              </div>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Per-strategy performance" bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-[11.5px]">
            <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left">Strategy</th>
                <th className="px-2 py-1.5 text-right">Signals</th>
                <th className="px-2 py-1.5 text-right">PnL Today</th>
                <th className="px-2 py-1.5 text-right">Drawdown</th>
                <th className="px-2 py-1.5 text-right">Alloc</th>
                <th className="px-2 py-1.5 text-right">Open</th>
              </tr>
            </thead>
            <tbody>
              {snap.strategies.map((s) => (
                <tr key={s.id} className="border-b border-panel-border/60">
                  <td className="px-3 py-1.5">{s.name}</td>
                  <td className="num px-2 py-1.5 text-right">{s.signalsToday}</td>
                  <td
                    className={`num px-2 py-1.5 text-right ${s.pnlToday >= 0 ? "text-profit" : "text-loss"}`}
                  >
                    {fmtMoney(s.pnlToday)}
                  </td>
                  <td className="num px-2 py-1.5 text-right text-loss">{fmtPct(s.drawdown)}</td>
                  <td className="num px-2 py-1.5 text-right">{s.allocationPct}%</td>
                  <td className="num px-2 py-1.5 text-right">{s.openPositions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function StatTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "crit" | "warn" | "neutral";
}) {
  const color =
    tone === "ok"
      ? "text-profit"
      : tone === "crit"
        ? "text-loss"
        : tone === "warn"
          ? "text-status-warn"
          : "text-foreground";
  return (
    <div className="rounded-sm border border-panel-border bg-panel-elevated p-2.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`num mt-0.5 text-base font-semibold ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function buildSparkPath(values: number[], w: number, h: number): string {
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? w / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = i * step;
      const y = h - ((v - min) / range) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}
