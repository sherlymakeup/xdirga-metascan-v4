import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CircleDot,
  Pause,
  Play,
  Power,
  ShieldOff,
  Square,
  Zap,
} from "lucide-react";
import { getRuntimeAdapter, useSnapshot } from "@/lib/adapters/runtime";
import { getRuntimeMode, useConnectionState } from "@/lib/runtime";
import { fmtDuration, fmtMoney, fmtNum, fmtPct, fmtPrice, relativeTime } from "@/lib/format";
import { MetricCard } from "@/components/cockpit/metric-card";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { RuntimeStateBadge } from "@/components/cockpit/runtime-state-badge";
import { ConfirmationDialog, type DangerLevel } from "@/components/cockpit/confirmation-dialog";
import { BrokerEnvironmentSummary, FixtureSourceNotice } from "@/components/runtime/environment-badges";
import { EmptyState } from "@/components/cockpit/states";
import { RiskMeter } from "@/components/cockpit/risk-meter";
import type { Alert, Position, SubsystemHealth } from "@/lib/types";
import type { RuntimeCommand, RuntimeCommand as Cmd } from "@/lib/adapters/runtime";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Cockpit · XDIRGA METASCAN" },
      { name: "description", content: "Primary operational cockpit for the local trading runtime." },
    ],
  }),
  component: CockpitPage,
});

interface ConfirmState {
  open: boolean;
  level: DangerLevel;
  title: string;
  description: string;
  impact?: React.ReactNode;
  phrase?: string;
  destructive?: boolean;
  command: Cmd;
  confirmLabel?: string;
}

function CockpitPage() {
  const snap = useSnapshot();
  const connection = useConnectionState();
  const isDemo = getRuntimeMode() === "fixture";
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);

  const critical = snap.alerts.filter((a) => !a.acknowledged && a.severity === "CRITICAL").length;
  const openExec = snap.orders.filter((o) => o.status === "EXECUTION_UNKNOWN").length;

  const runtime = snap.runtime;
  const canStart = runtime.state === "STOPPED" || runtime.state === "ERROR" || runtime.state === "DISCONNECTED";
  const canPause = runtime.state === "READY" || runtime.state === "DEGRADED";
  const canResume = runtime.state === "PAUSED";
  const canStop = ["READY", "DEGRADED", "PAUSED", "RECONNECTING"].includes(runtime.state);
  const canKill = runtime.state !== "KILLED" && runtime.state !== "STOPPED";

  const runCommand = async (cmd: RuntimeCommand) => {
    await getRuntimeAdapter().sendCommand(cmd);
  };

  return (
    <>
      <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
        <BrokerEnvironmentSummary />
        <FixtureSourceNotice entity="data" />
        {connection.state !== "CONNECTED" && (
          <div className="panel p-3 text-xs text-muted-foreground">{connection.state === "CONNECTING" ? "Loading authoritative snapshot…" : `Dashboard ${connection.state.toLowerCase()}`}</div>
        )}
        {!snap.accountAvailable && <div className="panel p-3 text-xs text-muted-foreground">Account unavailable</div>}
        {/* Header + primary controls */}
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="panel px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                  <CircleDot className="h-3 w-3 text-primary" />
                  Cockpit · Monitor. Control. Protect.
                </div>
                <h1 className="mt-0.5 truncate text-lg font-semibold">
                  {runtime.id} <span className="text-muted-foreground">·</span>{" "}
                  <span className="num text-sm text-muted-foreground">{runtime.sessionId}</span>
                </h1>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <StatusBadge tone={runtime.tradingMode === "LIVE" ? "crit" : "info"}>
                  {runtime.tradingMode}
                </StatusBadge>
                <span>uptime <span className="num text-foreground">{fmtDuration(runtime.uptimeSec)}</span></span>
                <span>started <span className="num text-foreground">{relativeTime(runtime.startedAt)}</span></span>
                <span>last sync <span className="num text-foreground">{relativeTime(snap.broker.lastRequestAt)}</span></span>
                <span>account observed <span className="num text-foreground">{snap.account.updatedAt ? relativeTime(snap.account.updatedAt) : "—"}</span></span>
              </div>
            </div>
          </div>

          {isDemo && <div className="panel flex flex-wrap items-center gap-1 px-2 py-1.5">
            <ControlButton
              icon={<Play className="h-3.5 w-3.5" />}
              disabled={!canStart}
              label="Start"
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 2,
                  title: "Start runtime",
                  description: "The runtime will connect to the broker gateway and begin evaluating strategies.",
                  impact: <span>Trading mode: {runtime.tradingMode}. Entries will remain disabled until confirmed.</span>,
                  command: { kind: "runtime.start" },
                  confirmLabel: "Start runtime",
                })
              }
            />
            <ControlButton
              icon={<Pause className="h-3.5 w-3.5" />}
              disabled={!canPause}
              label="Pause"
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 2,
                  title: "Pause runtime",
                  description: "New signals will be ignored. Open positions remain managed.",
                  command: { kind: "runtime.pause" },
                  confirmLabel: "Pause",
                })
              }
            />
            <ControlButton
              icon={<ArrowRight className="h-3.5 w-3.5" />}
              disabled={!canResume}
              label="Resume"
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 2,
                  title: "Resume runtime",
                  description: "Strategy evaluation and entries will resume.",
                  command: { kind: "runtime.resume" },
                  confirmLabel: "Resume",
                })
              }
            />
            <ControlButton
              icon={<Square className="h-3.5 w-3.5" />}
              disabled={!canStop}
              label="Stop"
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 3,
                  title: "Stop runtime",
                  description: "Runtime will finalize current operations and transition to STOPPED.",
                  impact: (
                    <ul className="list-disc pl-4">
                      <li>Broker connection closed</li>
                      <li>Open positions remain in the broker terminal</li>
                      <li>WebSocket bus terminated</li>
                    </ul>
                  ),
                  phrase: "STOP",
                  command: { kind: "runtime.stop" },
                  confirmLabel: "Stop runtime",
                })
              }
            />
            <ControlButton
              icon={<ShieldOff className="h-3.5 w-3.5" />}
              tone="warn"
              label={runtime.entriesEnabled ? "Disable Entries" : "Enable Entries"}
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 2,
                  title: runtime.entriesEnabled ? "Disable new entries" : "Enable new entries",
                  description: runtime.entriesEnabled
                    ? "Strategies will not open new positions. Position management continues."
                    : "Strategies may open new positions subject to risk and safety checks.",
                  command: runtime.entriesEnabled
                    ? { kind: "runtime.disableEntries" }
                    : { kind: "runtime.enableEntries" },
                  confirmLabel: runtime.entriesEnabled ? "Disable" : "Enable",
                })
              }
            />
            <ControlButton
              icon={<Zap className="h-3.5 w-3.5" />}
              tone="crit"
              disabled={!canKill}
              label="Emergency Kill"
              onClick={() =>
                setConfirm({
                  open: true,
                  level: 4,
                  destructive: true,
                  title: "Execute emergency kill procedure",
                  description:
                    "This halts the runtime immediately. Broker-side positions must be reconciled after execution.",
                  impact: (
                    <div className="space-y-1">
                      <div>· Stop new entries</div>
                      <div>· Cancel all pending orders ({snap.orders.filter((o) => o.status === "ACKNOWLEDGED").length})</div>
                      <div>· Attempt to close all open positions ({snap.positions.length})</div>
                      <div>· Stop all strategies ({snap.strategies.length})</div>
                      <div>· Stop runtime process</div>
                    </div>
                  ),
                  phrase: "EMERGENCY-KILL",
                  command: {
                    kind: "runtime.emergencyKill",
                    reason: "operator",
                    steps: ["disable_entries", "cancel_orders", "close_positions", "stop_runtime"],
                  },
                  confirmLabel: "Execute Kill",
                })
              }
            />
          </div>}
        </div>

        {/* Overview metrics */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <MetricCard
            label="Balance"
            value={fmtMoney(snap.account.balance)}
            hint={snap.account.currency}
            freshness={snap.account.freshness}
          />
          <MetricCard
            label="Equity"
            value={fmtMoney(snap.account.equity)}
            delta={snap.account.equity - snap.account.balance}
            deltaLabel="vs balance"
            freshness={snap.account.freshness}
          />
          <MetricCard
            label="Floating PnL"
            value={snap.account.floatingPnl == null ? "—" : fmtMoney(snap.account.floatingPnl)}
            tone={snap.account.floatingPnl == null ? undefined : snap.account.floatingPnl >= 0 ? "ok" : "crit"}
            hint={snap.account.openPositions == null ? "—" : `${snap.account.openPositions} open`}
          />
          <MetricCard
            label="Realized Today"
            value={fmtMoney(snap.account.realizedPnlToday)}
            tone={snap.account.realizedPnlToday >= 0 ? "ok" : "crit"}
            hint={`${snap.account.tradesToday} trades · win ${fmtNum(snap.account.winRate, 1)}%`}
          />
          <MetricCard
            label="Daily Drawdown"
            value={fmtMoney(snap.account.dailyDrawdown)}
            tone={snap.account.dailyDrawdown < -300 ? "crit" : snap.account.dailyDrawdown < 0 ? "warn" : "ok"}
            hint={`max ${fmtPct(snap.account.maxDrawdown)}`}
          />
          <MetricCard
            label="Risk Utilization"
            value={`${fmtNum(snap.account.riskUtilization, 0)}%`}
            tone={snap.account.riskUtilization > 80 ? "crit" : snap.account.riskUtilization > 60 ? "warn" : "ok"}
            hint={`margin lvl ${fmtNum(snap.account.marginLevel, 0)}%`}
          />
        </div>

        {/* Main workspace */}
        <div className="grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
          <div className="space-y-3">
            <EquityPanel snap={snap} />
            <PositionsPanel positions={snap.positions} />
            <RuntimeHealthPanel subsystems={snap.subsystems} />
          </div>

          <div className="space-y-3">
            {(critical > 0 || openExec > 0) && (
              <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-3 text-xs">
                <div className="flex items-center gap-2 text-status-crit">
                  <Activity className="h-4 w-4" />
                  <span className="font-semibold uppercase tracking-wider">Attention required</span>
                </div>
                <ul className="mt-2 space-y-1 text-status-crit">
                  {critical > 0 && <li>· {critical} unresolved CRITICAL alert{critical > 1 ? "s" : ""}</li>}
                  {openExec > 0 && (
                    <li>· {openExec} order{openExec > 1 ? "s" : ""} in EXECUTION_UNKNOWN — do not retry</li>
                  )}
                </ul>
              </div>
            )}

            <ActiveStrategyPanel snap={snap} />
            <AlertsPanel alerts={snap.alerts} />
            <ActivityTimeline events={snap.events.slice(0, 8)} />
          </div>
        </div>
      </div>

      {isDemo && confirm && (
        <ConfirmationDialog
          open={confirm.open}
          onOpenChange={(v) => setConfirm(v ? confirm : null)}
          level={confirm.level}
          title={confirm.title}
          description={confirm.description}
          impactSummary={confirm.impact}
          confirmPhrase={confirm.phrase}
          confirmLabel={confirm.confirmLabel}
          destructive={confirm.destructive}
          onConfirm={async () => {
            await runCommand(confirm.command);
          }}
        />
      )}
    </>
  );
}

function ControlButton({
  icon,
  label,
  onClick,
  disabled,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "warn" | "crit";
}) {
  const toneCls =
    tone === "crit"
      ? "border-status-crit/40 text-status-crit hover:bg-status-crit/10"
      : tone === "warn"
        ? "border-status-warn/40 text-status-warn hover:bg-status-warn/10"
        : "border-panel-border hover:bg-muted";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-sm border bg-panel-elevated px-2 py-1.5 text-[11px] font-medium disabled:cursor-not-allowed disabled:opacity-30 ${toneCls}`}
    >
      {icon}
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}

function EquityPanel({ snap }: { snap: ReturnType<typeof useSnapshot> }) {
  const [tab, setTab] = useState<"equity" | "balance" | "floating" | "drawdown">("equity");
  const [range, setRange] = useState<"1H" | "4H" | "1D" | "1W" | "1M">("1D");

  const data = snap.equityCurve;
  const values = data.map((d) =>
    tab === "equity" ? d.equity : tab === "balance" ? d.balance : tab === "floating" ? d.floatingPnl : d.drawdown,
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range01 = (v: number) => (max === min ? 0.5 : (v - min) / (max - min));
  const path = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${(1 - range01(v)) * 100}`)
    .join(" ");

  const tabs: Array<[typeof tab, string]> = [
    ["equity", "Equity"],
    ["balance", "Balance"],
    ["floating", "Unrealized"],
    ["drawdown", "Drawdown"],
  ];

  return (
    <Panel
      title="Equity & PnL"
      subtitle={`${data.length} points · ${range} view`}
      toolbar={
        <div className="flex items-center gap-1">
          {(["1H", "4H", "1D", "1W", "1M"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`num rounded-sm px-1.5 py-0.5 text-[10.5px] ${
                range === r ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/50"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      }
      bodyClassName="p-0"
    >
      <div className="flex items-center gap-1 border-b border-panel-border px-3 py-1.5">
        {tabs.map(([k, l]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`rounded-sm px-2 py-1 text-[11px] ${
              tab === k ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {l}
          </button>
        ))}
        <div className="num ml-auto text-[11px] text-muted-foreground">
          latest <span className="text-foreground">{fmtMoney(values[values.length - 1] ?? 0)}</span>
        </div>
      </div>
      <div className="relative h-56 w-full px-2 py-2">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
          <defs>
            <linearGradient id="grad" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.35" />
              <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((y) => (
            <line key={y} x1="0" x2="100" y1={y * 100} y2={y * 100} stroke="var(--color-grid)" strokeWidth="0.2" />
          ))}
          <polygon
            points={`0,100 ${path} 100,100`}
            fill="url(#grad)"
          />
          <polyline points={path} fill="none" stroke="var(--color-primary)" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
    </Panel>
  );
}

function PositionsPanel({ positions }: { positions: Position[] }) {
  return (
    <Panel
      title="Open Positions"
      subtitle={`${positions.length} open`}
      toolbar={<StatusBadge tone="info" size="sm">live</StatusBadge>}
      bodyClassName="p-0"
    >
      {positions.length === 0 ? (
        <EmptyState title="No open positions" description="Strategies have no active exposure." />
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left">Symbol</th>
                  <th className="px-2 py-1.5 text-left">Side</th>
                  <th className="px-2 py-1.5 text-right">Vol</th>
                  <th className="px-2 py-1.5 text-right">Entry</th>
                  <th className="px-2 py-1.5 text-right">Current</th>
                  <th className="px-2 py-1.5 text-right">SL / TP</th>
                  <th className="px-2 py-1.5 text-right">Float PnL</th>
                  <th className="px-2 py-1.5 text-right">R</th>
                  <th className="px-2 py-1.5 text-left">Strategy</th>
                  <th className="px-2 py-1.5 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className="border-b border-panel-border/60 hover:bg-muted/40">
                    <td className="num px-3 py-1.5 font-semibold">{p.symbol}</td>
                    <td className="px-2 py-1.5">
                      <StatusBadge tone={p.side === "BUY" ? "ok" : "crit"} size="sm">
                        {p.side}
                      </StatusBadge>
                    </td>
                    <td className="num px-2 py-1.5 text-right">{fmtNum(p.volume, 2)}</td>
                    <td className="num px-2 py-1.5 text-right">{fmtPrice(p.entryPrice)}</td>
                    <td className="num px-2 py-1.5 text-right">{fmtPrice(p.currentPrice)}</td>
                    <td className="num px-2 py-1.5 text-right text-muted-foreground">
                      {p.stopLoss ? fmtPrice(p.stopLoss) : <span className="text-status-crit">—</span>} /{" "}
                      {p.takeProfit ? fmtPrice(p.takeProfit) : "—"}
                    </td>
                    <td className={`num px-2 py-1.5 text-right ${p.floatingPnl >= 0 ? "text-profit" : "text-loss"}`}>
                      {fmtMoney(p.floatingPnl)}
                    </td>
                    <td className="num px-2 py-1.5 text-right">{fmtNum(p.rMultiple, 2)}R</td>
                    <td className="px-2 py-1.5 text-muted-foreground">{p.strategy}</td>
                    <td className="px-2 py-1.5">
                      <ProtectionBadge protection={p.protection} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="grid gap-2 p-2 md:hidden">
            {positions.map((p) => (
              <div key={p.id} className="rounded-sm border border-panel-border bg-panel-elevated p-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="num font-semibold">{p.symbol}</span>
                    <StatusBadge tone={p.side === "BUY" ? "ok" : "crit"} size="sm">
                      {p.side} {fmtNum(p.volume, 2)}
                    </StatusBadge>
                  </div>
                  <span className={`num text-sm ${p.floatingPnl >= 0 ? "text-profit" : "text-loss"}`}>
                    {fmtMoney(p.floatingPnl)}
                  </span>
                </div>
                <div className="mt-1 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                  <div>Entry <div className="num text-foreground">{fmtPrice(p.entryPrice)}</div></div>
                  <div>Now <div className="num text-foreground">{fmtPrice(p.currentPrice)}</div></div>
                  <div>SL <div className={`num ${p.stopLoss ? "text-foreground" : "text-status-crit"}`}>{p.stopLoss ? fmtPrice(p.stopLoss) : "—"}</div></div>
                </div>
                <div className="mt-1.5 flex items-center justify-between">
                  <ProtectionBadge protection={p.protection} />
                  <span className="text-[10px] text-muted-foreground">{p.strategy}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

function ProtectionBadge({ protection }: { protection: Position["protection"] }) {
  const map: Record<Position["protection"], { tone: StatusTone; label: string }> = {
    PROTECTED: { tone: "ok", label: "Protected" },
    PARTIALLY_PROTECTED: { tone: "warn", label: "Partial" },
    UNPROTECTED: { tone: "crit", label: "Unprotected" },
    INVALID_PROTECTION: { tone: "crit", label: "Invalid" },
    UNKNOWN: { tone: "neutral", label: "Unknown" },
  };
  const m = map[protection];
  return (
    <StatusBadge tone={m.tone} size="sm">
      {m.label}
    </StatusBadge>
  );
}

function RuntimeHealthPanel({ subsystems }: { subsystems: SubsystemHealth[] }) {
  return (
    <Panel title="Runtime Health" subtitle="10 subsystems">
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-3 lg:grid-cols-5">
        {subsystems.map((s) => {
          const tone: StatusTone =
            s.state === "OK" ? "ok" : s.state === "DEGRADED" ? "warn" : s.state === "DOWN" ? "crit" : "neutral";
          return (
            <div key={s.key} className="rounded-sm border border-panel-border bg-panel-elevated p-2">
              <div className="flex items-center justify-between">
                <span className="truncate text-[11px] font-medium">{s.label}</span>
                <StatusBadge tone={tone} size="sm">{s.state}</StatusBadge>
              </div>
              <div className="mt-1 flex items-center justify-between text-[10.5px] text-muted-foreground">
                <span>hb {relativeTime(s.lastHeartbeatAt)}</span>
                <span className="num">{s.latencyMs != null ? `${s.latencyMs}ms` : "—"}</span>
              </div>
              {s.lastError && (
                <div className="mt-1 truncate text-[10px] text-status-crit" title={s.lastError}>
                  {s.lastError}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function ActiveStrategyPanel({ snap }: { snap: ReturnType<typeof useSnapshot> }) {
  const s = snap.strategies.find((x) => x.status === "ACTIVE") ?? snap.strategies[0];
  const meters = useMemo(() => {
    return [
      { label: "Confidence", value: s.confidence * 100, warnAt: 30, breachAt: 20, disp: `${(s.confidence * 100).toFixed(0)}%`, inverted: true },
      { label: "Allocation used", value: s.allocationPct, warnAt: 80, breachAt: 100, disp: `${s.allocationPct}%` },
    ];
  }, [s]);
  return (
    <Panel
      title="Active Strategy"
      subtitle={s.name}
      toolbar={<StatusBadge tone={s.status === "ACTIVE" ? "ok" : s.status === "PAUSED" ? "warn" : "neutral"} size="sm">{s.status}</StatusBadge>}
    >
      <div className="space-y-2.5 text-[11.5px]">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
          <span>ID <span className="num text-foreground">{s.id}</span></span>
          <span>v<span className="num text-foreground">{s.version}</span></span>
          <span>{s.symbols.join(", ")} · {s.timeframe}</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">Bias</div>
            <StatusBadge tone={s.currentBias === "LONG" ? "ok" : s.currentBias === "SHORT" ? "crit" : "neutral"} size="sm">
              {s.currentBias}
            </StatusBadge>
          </div>
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">PnL Today</div>
            <div className={`num ${s.pnlToday >= 0 ? "text-profit" : "text-loss"}`}>{fmtMoney(s.pnlToday)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">Signals</div>
            <div className="num">{s.signalsToday}</div>
          </div>
        </div>
        <div className="space-y-2">
          {meters.map((m) => (
            <RiskMeter
              key={m.label}
              label={m.label}
              value={m.value}
              warnAt={m.warnAt}
              breachAt={m.breachAt}
              displayValue={m.disp}
              inverted={m.inverted}
            />
          ))}
        </div>
      </div>
    </Panel>
  );
}

function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  const isDemo = getRuntimeMode() === "fixture";
  return (
    <Panel
      title="Active Alerts"
      subtitle={`${alerts.filter((a) => !a.acknowledged).length} unresolved`}
      scroll
      bodyClassName="p-0 max-h-80"
    >
      {alerts.length === 0 ? (
        <EmptyState title="No active alerts" description="Runtime and safety systems are quiet." />
      ) : (
        <ul className="divide-y divide-panel-border">
          {alerts.map((a) => {
            const tone: StatusTone =
              a.severity === "CRITICAL" ? "crit" : a.severity === "HIGH" ? "crit" : a.severity === "MEDIUM" ? "warn" : "info";
            return (
              <li key={a.id} className={`p-2.5 text-[11.5px] ${a.acknowledged ? "opacity-60" : ""}`}>
                <div className="flex items-start gap-2">
                  <StatusBadge tone={tone} size="sm">{a.severity}</StatusBadge>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{a.title}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">{a.description}</div>
                    <div className="mt-1 flex items-center justify-between text-[10.5px] text-muted-foreground">
                      <span>{a.source} · {relativeTime(a.createdAt)}</span>
                      {isDemo && !a.acknowledged && (
                        <button
                          onClick={() => getRuntimeAdapter().sendCommand({ kind: "alert.acknowledge", id: a.id })}
                          className="rounded-sm border border-panel-border px-1.5 py-0.5 hover:bg-muted"
                        >
                          Acknowledge
                        </button>
                      )}
                    </div>
                    <div className="mt-1 text-[10.5px] text-status-info">→ {a.suggestedAction}</div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function ActivityTimeline({ events }: { events: ReturnType<typeof useSnapshot>["events"] }) {
  return (
    <Panel title="Recent Activity" subtitle={`${events.length} events`} scroll bodyClassName="p-0 max-h-64">
      <ol className="divide-y divide-panel-border">
        {events.map((e) => {
          const tone: StatusTone =
            e.severity === "CRITICAL" || e.severity === "ERROR"
              ? "crit"
              : e.severity === "WARNING"
                ? "warn"
                : "info";
          return (
            <li key={e.id} className="grid grid-cols-[auto_auto_1fr] items-baseline gap-2 px-3 py-1.5 text-[11px]">
              <span className="num text-muted-foreground">{relativeTime(e.at)}</span>
              <StatusBadge tone={tone} size="sm">{e.severity}</StatusBadge>
              <span className="truncate">
                <span className="text-muted-foreground">{e.component}</span> · {e.message}
              </span>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}
