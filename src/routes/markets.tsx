import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search, Star, TrendingDown, TrendingUp } from "lucide-react";
import { useSnapshot } from "@/lib/adapters/runtime";
import { fmtNum, fmtPct, fmtPrice, relativeTime } from "@/lib/format";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge } from "@/components/cockpit/status-badge";
import { cn } from "@/lib/utils";
import type { MarketSymbol } from "@/lib/types";

export const Route = createFileRoute("/markets")({
  head: () => ({
    meta: [
      { title: "Markets · XDIRGA METASCAN" },
      { name: "description", content: "Market data monitoring for the local trading runtime." },
    ],
  }),
  component: MarketsPage,
});

type Group = "ALL" | MarketSymbol["group"];
type SortKey = "symbol" | "bid" | "spread" | "changePct" | "tickAgeMs";
type SortDir = "asc" | "desc";

const GROUPS: Group[] = ["ALL", "FX", "METALS", "INDICES", "CRYPTO"];

export function marketPulse(markets: MarketSymbol[]) {
  const groups: MarketSymbol["group"][] = ["FX", "METALS", "INDICES", "CRYPTO"];
  return groups.map((group) => {
    const list = markets.filter((market) => market.group === group);
    const observed = list.filter((market) => market.changePct != null);
    const up = observed.filter((market) => market.changePct! >= 0).length;
    const avg = observed.length ? observed.reduce((sum, market) => sum + market.changePct!, 0) / observed.length : null;
    return {
      group,
      total: list.length,
      observed: observed.length,
      up,
      down: observed.length - up,
      avg,
      stale: list.filter((market) => market.freshness !== "FRESH").length,
      breadthPct: observed.length ? (up / observed.length) * 100 : 0,
    };
  });
}

function seededSpark(sym: string, base: number, changePct: number): number[] {
  let s = 0;
  for (let i = 0; i < sym.length; i++) s = (s * 31 + sym.charCodeAt(i)) >>> 0;
  const pts: number[] = [];
  const drift = (base * changePct) / 100 / 30;
  let v = base - drift * 30;
  for (let i = 0; i < 30; i++) {
    s = (s * 1103515245 + 12345) >>> 0;
    const noise = ((s % 1000) / 1000 - 0.5) * base * 0.0015;
    v += drift + noise;
    pts.push(v);
  }
  return pts;
}

function Sparkline({ pts, up }: { pts: number[]; up: boolean }) {
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const w = 72;
  const h = 20;
  const step = w / (pts.length - 1);
  const d = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((p - min) / span) * h).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={w} height={h} className={cn("block", up ? "text-profit" : "text-loss")}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}


function pipValue(m: MarketSymbol): number {
  // rough pip factor: FX = 10000, JPY-like or others = 100, crypto/indices raw
  if (m.group === "FX") return (m.symbol.includes("JPY") ? 100 : 10000);
  if (m.group === "METALS") return 100;
  return 1;
}

function MarketsPage() {
  const snap = useSnapshot();
  const [group, setGroup] = useState<Group>("ALL");
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<MarketSymbol | null>(snap.markets[0] ?? null);
  const [tf, setTf] = useState("M15");

  const filtered = useMemo(() => {
    const list = snap.markets.filter(
      (m) => (group === "ALL" || m.group === group) && m.symbol.toLowerCase().includes(q.toLowerCase()),
    );
    const dir = sortDir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [snap.markets, group, q, sortKey, sortDir]);

  const pulse = useMemo(() => marketPulse(snap.markets), [snap.markets]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(k);
      setSortDir(k === "symbol" ? "asc" : "desc");
    }
  };

  const toggleFav = (sym: string) => {
    const next = new Set(favs);
    next.has(sym) ? next.delete(sym) : next.add(sym);
    setFavs(next);
  };

  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      {/* Market pulse strip */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {pulse.map((p) => {
           const up = p.avg != null && p.avg >= 0;

          return (
            <button
              key={p.group}
              onClick={() => setGroup(p.group)}
              className={cn(
                "group rounded-sm border bg-panel-elevated p-2.5 text-left transition-colors",
                group === p.group ? "border-foreground/40" : "border-panel-border hover:border-panel-border/80",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{p.group}</span>
                <span className="num text-[10px] text-muted-foreground">{p.total}</span>
              </div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className={cn("num text-base font-semibold", up ? "text-profit" : "text-loss")}>
                  {fmtPct(p.avg, 2)}
                </span>
                 {p.avg != null && (up ? <TrendingUp className="h-3 w-3 text-profit" /> : <TrendingDown className="h-3 w-3 text-loss" />)}

              </div>
              <div className="mt-1.5 flex h-1 overflow-hidden rounded-full bg-muted/60">
                <div className="bg-profit" style={{ width: `${p.breadthPct}%` }} />
                <div className="bg-loss" style={{ width: `${100 - p.breadthPct}%` }} />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
                <span className="num text-profit">↑{p.up}</span>
                {p.stale > 0 && <span className="num text-status-warn">{p.stale} stale</span>}
                <span className="num text-loss">↓{p.down}</span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(340px,420px)]">
        <Panel
          bodyClassName="p-0"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-panel-border px-3 py-2">
            <div className="flex min-w-0 items-center gap-3">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Watchlist</div>
                <div className="mt-0.5 text-xs">
                  <span className="num font-semibold">{filtered.length}</span>{" "}
                  <span className="text-muted-foreground">symbols</span>
                  {favs.size > 0 && (
                    <span className="ml-2 text-muted-foreground">
                      · <span className="num text-foreground">{favs.size}</span> starred
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {GROUPS.map((g) => (
                <button
                  key={g}
                  onClick={() => setGroup(g)}
                  className={cn(
                    "rounded-sm border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
                    group === g
                      ? "border-foreground/40 bg-muted text-foreground"
                      : "border-transparent text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2 border-b border-panel-border px-3 py-1.5">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search symbols…"
              className="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-[11.5px]">
              <thead className="sticky top-0 border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="w-6 px-2 py-1.5"></th>
                  <SortTh label="Symbol" active={sortKey === "symbol"} dir={sortDir} onClick={() => toggleSort("symbol")} align="left" />
                  <SortTh label="Bid" active={sortKey === "bid"} dir={sortDir} onClick={() => toggleSort("bid")} />
                  <th className="px-2 py-1.5 text-right">Ask</th>
                  <SortTh label="Spread" active={sortKey === "spread"} dir={sortDir} onClick={() => toggleSort("spread")} />
                  <SortTh label="Chg %" active={sortKey === "changePct"} dir={sortDir} onClick={() => toggleSort("changePct")} />
                  <th className="px-2 py-1.5 text-center">30-tick</th>
                  <SortTh label="Tick" active={sortKey === "tickAgeMs"} dir={sortDir} onClick={() => toggleSort("tickAgeMs")} />
                </tr>
              </thead>
              <tbody>
                {filtered.map((m) => {
                  const pts = m.changePct == null ? null : seededSpark(m.symbol, m.last, m.changePct);
                  const up = m.changePct != null && m.changePct >= 0;
                  const isSel = selected?.symbol === m.symbol;
                  const isFav = favs.has(m.symbol);
                  return (
                    <tr
                      key={m.symbol}
                      onClick={() => setSelected(m)}
                      className={cn(
                        "cursor-pointer border-b border-panel-border/50 transition-colors",
                        isSel ? "bg-muted/60" : "hover:bg-muted/25",
                      )}
                    >
                      <td className="px-2 py-1.5">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleFav(m.symbol);
                          }}
                          className="text-muted-foreground/60 hover:text-status-warn"
                        >
                          <Star className={cn("h-3 w-3", isFav && "fill-status-warn text-status-warn")} />
                        </button>
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              "h-1.5 w-1.5 rounded-full",
                              m.sessionOpen ? "bg-status-ok" : "bg-muted-foreground/50",
                            )}
                          />
                          <span className="num font-semibold tracking-tight">{m.symbol}</span>
                          {!m.tradingPermitted && (
                            <span className="rounded-sm bg-status-crit/15 px-1 text-[9px] font-bold text-status-crit">LOCK</span>
                          )}
                        </div>
                      </td>
                      <td className="num px-2 py-1.5 text-right">{fmtPrice(m.bid, 5)}</td>
                      <td className="num px-2 py-1.5 text-right text-muted-foreground">{fmtPrice(m.ask, 5)}</td>
                      <td className="num px-2 py-1.5 text-right text-muted-foreground">
                        {fmtNum(m.spread * pipValue(m), 1)}
                        <span className="ml-0.5 text-[9px] opacity-60">p</span>
                      </td>
                      <td className={cn("num px-2 py-1.5 text-right font-medium", up ? "text-profit" : "text-loss")}>
                        <span className="inline-flex items-center gap-0.5">
                          {m.changePct != null && (up ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
                          {fmtPct(m.changePct == null ? null : Math.abs(m.changePct), 2)}
                        </span>
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex justify-center">
                          {pts ? <Sparkline pts={pts} up={up} /> : "—"}
                        </div>
                      </td>
                      <td className="px-2 py-1.5">
                        <StatusBadge tone={m.freshness === "FRESH" ? "ok" : "warn"} size="sm">
                          {m.tickAgeMs}ms
                        </StatusBadge>
                      </td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-3 py-8 text-center text-xs text-muted-foreground">
                      No symbols match the current filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        {selected && <SymbolDetail symbol={selected} />}
      </div>

      <Panel
        title="Chart Workspace"
        subtitle={selected?.symbol ?? "—"}
        toolbar={
          <div className="flex items-center gap-1">
            {["M1", "M5", "M15", "H1", "H4", "D1"].map((t) => (
              <button
                key={t}
                onClick={() => setTf(t)}
                className={cn(
                  "rounded-sm border px-1.5 py-0.5 text-[10px] font-medium",
                  tf === t
                    ? "border-foreground/40 bg-muted text-foreground"
                    : "border-panel-border bg-panel-elevated text-muted-foreground hover:text-foreground",
                )}
              >
                {t}
              </button>
            ))}
          </div>
        }
      >
        <div className="scan-grid relative h-72 overflow-hidden rounded-sm border border-panel-border bg-background">
          {selected && (
            <ChartMock symbol={selected} tf={tf} />
          )}
        </div>
      </Panel>
    </div>
  );
}

function SortTh({
  label,
  active,
  dir,
  onClick,
  align = "right",
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: "left" | "right";
}) {
  const Icon = !active ? ArrowUpDown : dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className={cn("px-2 py-1.5", align === "left" ? "text-left" : "text-right")}>
      <button
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground",
          active && "text-foreground",
        )}
      >
        {label}
        <Icon className="h-2.5 w-2.5 opacity-70" />
      </button>
    </th>
  );
}

function ChartMock({ symbol, tf }: { symbol: MarketSymbol; tf: string }) {
  if (symbol.changePct == null) return <div className="flex h-full items-center justify-center text-xs text-muted-foreground">N/A</div>;
  const pts = seededSpark(symbol.symbol + tf, symbol.last, symbol.changePct);
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const w = 1000;
  const h = 260;
  const step = w / (pts.length - 1);
  const d = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((p - min) / span) * h * 0.85 - 15).toFixed(1)}`)
    .join(" ");
  const up = symbol.changePct >= 0;
  return (
    <>
      <div className="absolute left-2 top-2 flex items-baseline gap-2">
        <span className="num text-lg font-semibold">{fmtPrice(symbol.last)}</span>
        <span className={cn("num text-xs", up ? "text-profit" : "text-loss")}>{fmtPct(symbol.changePct)}</span>
      </div>
      <div className="absolute right-2 top-2 text-[10px] uppercase tracking-widest text-muted-foreground">
        {tf} · mock feed
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className={cn("absolute inset-0 h-full w-full", up ? "text-profit" : "text-loss")}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={`chartFill-${symbol.symbol}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${d} L${w},${h} L0,${h} Z`} fill={`url(#chartFill-${symbol.symbol})`} />
        <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <div className="absolute bottom-2 left-2 text-[10px] text-muted-foreground">
        integrate broker feed · candlestick renderer slot
      </div>
    </>
  );
}

function SymbolDetail({ symbol }: { symbol: MarketSymbol }) {
  const up = symbol.changePct != null && symbol.changePct >= 0;
  const pip = pipValue(symbol);
  const spreadPips = symbol.spread * pip;
  const rows: Array<[string, string]> = [
    ["Contract size", fmtNum(symbol.contractSize, 0)],
    ["Tick size", String(symbol.tickSize)],
    ["Vol range", `${symbol.minVolume} – ${symbol.maxVolume}`],
    ["Vol step", String(symbol.volumeStep)],
    ["Swap L / S", `${symbol.swapLong} / ${symbol.swapShort}`],
    ["Margin", `${symbol.marginRequirement}%`],
  ];

  // Mock depth-of-market ladder around bid/ask
  const ladder = Array.from({ length: 5 }, (_, i) => {
    const bid = symbol.bid - i * symbol.tickSize * 2;
    const ask = symbol.ask + i * symbol.tickSize * 2;
    const bidVol = 25 - i * 4 + ((symbol.symbol.charCodeAt(0) + i) % 7);
    const askVol = 22 - i * 3 + ((symbol.symbol.charCodeAt(1) + i) % 8);
    return { bid, ask, bidVol: Math.max(1, bidVol), askVol: Math.max(1, askVol) };
  });
  const maxVol = Math.max(...ladder.flatMap((l) => [l.bidVol, l.askVol]));

  return (
    <Panel
      bodyClassName="p-0"
    >
      <div className="flex items-start justify-between gap-2 border-b border-panel-border px-3 py-2">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            {symbol.group} · Instrument
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="num text-sm font-semibold tracking-tight">{symbol.symbol}</span>
            <span
              className={cn(
                "rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider",
                symbol.sessionOpen
                  ? "bg-status-ok/15 text-status-ok"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {symbol.sessionOpen ? "Session Open" : "Session Closed"}
            </span>
          </div>
        </div>
        <StatusBadge tone={symbol.freshness === "FRESH" ? "ok" : "warn"} size="sm">
          {symbol.freshness}
        </StatusBadge>
      </div>

      <div className="grid grid-cols-3 divide-x divide-panel-border border-b border-panel-border bg-panel-elevated/40">
        <div className="p-2.5">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Bid</div>
          <div className="num mt-0.5 text-base font-semibold text-loss">{fmtPrice(symbol.bid)}</div>
        </div>
        <div className="p-2.5">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Ask</div>
          <div className="num mt-0.5 text-base font-semibold text-profit">{fmtPrice(symbol.ask)}</div>
        </div>
        <div className="p-2.5">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Change</div>
          <div className={cn("num mt-0.5 text-base font-semibold", up ? "text-profit" : "text-loss")}>
            {fmtPct(symbol.changePct)}
          </div>
        </div>
      </div>

      <div className="border-b border-panel-border px-3 py-2">
        <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>Spread</span>
          <span className="num text-foreground">{fmtNum(spreadPips, 1)} pips</span>
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted/60">
          <div
            className={cn("h-full", spreadPips > 3 ? "bg-status-warn" : "bg-status-ok")}
            style={{ width: `${Math.min(100, (spreadPips / 5) * 100)}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[9px] text-muted-foreground">
          <span>tight</span>
          <span>wide</span>
        </div>
      </div>

      <div className="border-b border-panel-border px-3 py-2">
        <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Depth of Market <span className="text-muted-foreground/60">(mock)</span>
        </div>
        <div className="space-y-0.5">
          {ladder.map((l, i) => (
            <div key={i} className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-[11px]">
              <div className="relative h-4 overflow-hidden rounded-sm bg-loss/5">
                <div
                  className="absolute inset-y-0 right-0 bg-loss/25"
                  style={{ width: `${(l.bidVol / maxVol) * 100}%` }}
                />
                <div className="relative flex h-full items-center justify-between px-1.5">
                  <span className="num text-[10px] text-muted-foreground">{l.bidVol}</span>
                  <span className="num text-loss">{fmtPrice(l.bid, 5)}</span>
                </div>
              </div>
              <div className="num text-[9px] text-muted-foreground">L{i + 1}</div>
              <div className="relative h-4 overflow-hidden rounded-sm bg-profit/5">
                <div
                  className="absolute inset-y-0 left-0 bg-profit/25"
                  style={{ width: `${(l.askVol / maxVol) * 100}%` }}
                />
                <div className="relative flex h-full items-center justify-between px-1.5">
                  <span className="num text-profit">{fmtPrice(l.ask, 5)}</span>
                  <span className="num text-[10px] text-muted-foreground">{l.askVol}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="px-3 py-2">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Specifications
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
          {rows.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between border-b border-panel-border/40 py-1">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="num">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
          <span>
            Last tick <span className="num text-foreground">{symbol.tickAgeMs}ms</span>
          </span>
          <span>
            Trading{" "}
            <span className={cn("num font-semibold", symbol.tradingPermitted ? "text-status-ok" : "text-status-crit")}>
              {symbol.tradingPermitted ? "Permitted" : "Blocked"}
            </span>
          </span>
        </div>
      </div>
    </Panel>
  );
}

// silence unused warning for helper kept for future use
void relativeTime;
