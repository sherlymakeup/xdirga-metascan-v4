import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, CheckCheck, X, Pause, Play, Trash2 } from "lucide-react";
import { useSnapshot, getRuntimeAdapter } from "@/lib/adapters/runtime";
import {
  useEventHistory,
  useEventHistoryPaused,
  eventHistoryStore,
} from "@/lib/runtime/events";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { EmptyState } from "@/components/cockpit/states";
import { CommandButton } from "@/components/commands/CommandButton";
import { relativeTime, fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Alert, LogSeverity, Severity } from "@/lib/types";
import type { EventSeverity } from "@/lib/runtime/events";


export const Route = createFileRoute("/events")({
  head: () => ({
    meta: [
      { title: "Events & Alerts · XDIRGA METASCAN" },
      { name: "description", content: "Runtime event stream and alerts inbox." },
    ],
  }),
  component: EventsPage,
});

const sevTone = (s: Severity): StatusTone =>
  s === "CRITICAL" || s === "HIGH" ? "crit" : s === "MEDIUM" ? "warn" : s === "LOW" ? "info" : "neutral";

const logTone = (s: LogSeverity): StatusTone =>
  s === "CRITICAL" || s === "ERROR" ? "crit" : s === "WARNING" ? "warn" : s === "INFO" ? "info" : "neutral";

const sevAccent: Record<Severity, string> = {
  CRITICAL: "bg-status-crit",
  HIGH: "bg-status-crit/80",
  MEDIUM: "bg-status-warn",
  LOW: "bg-status-info",
  INFO: "bg-muted-foreground/40",
};

function dayKey(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === y.toDateString();
  const prefix = isToday ? "Today" : isYesterday ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "short" });
  return `${prefix} — ${d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }).toUpperCase()}`;
}

function EventsPage() {
  const snap = useSnapshot();
  const [tab, setTab] = useState<"alerts" | "events" | "incidents" | "live">("alerts");
  const liveEvents = useEventHistory();
  const livePauseState = useEventHistoryPaused();
  const [liveSevFilter, setLiveSevFilter] = useState<"ALL" | EventSeverity>("ALL");
  const [severityFilter, setSeverityFilter] = useState<"ALL" | Severity>("ALL");
  const [sourceFilter, setSourceFilter] = useState<string>("ALL");
  const [logSeverity, setLogSeverity] = useState<"ALL" | LogSeverity>("ALL");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(snap.alerts[0]?.id ?? null);
  const [showAckd, setShowAckd] = useState(true);

  const counts = useMemo(() => {
    const c = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 } as Record<Severity, number>;
    for (const a of snap.alerts) if (!a.acknowledged) c[a.severity]++;
    return c;
  }, [snap.alerts]);

  const sources = useMemo(() => {
    const s = new Set<string>();
    snap.alerts.forEach((a) => s.add(a.source));
    return Array.from(s);
  }, [snap.alerts]);

  const filteredAlerts = useMemo(() => {
    const q = query.trim().toLowerCase();
    return snap.alerts.filter((a) => {
      if (!showAckd && a.acknowledged) return false;
      if (severityFilter !== "ALL" && a.severity !== severityFilter) return false;
      if (sourceFilter !== "ALL" && a.source !== sourceFilter) return false;
      if (q && !(a.title.toLowerCase().includes(q) || a.description.toLowerCase().includes(q) || a.source.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [snap.alerts, severityFilter, sourceFilter, query, showAckd]);

  const grouped = useMemo(() => {
    const map = new Map<string, Alert[]>();
    for (const a of filteredAlerts) {
      const k = dayKey(a.createdAt);
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(a);
    }
    return Array.from(map.entries());
  }, [filteredAlerts]);

  const selected = filteredAlerts.find((a) => a.id === selectedId) ?? filteredAlerts[0] ?? null;

  const unresolvedCrit = snap.alerts.filter((a) => !a.acknowledged && (a.severity === "CRITICAL" || a.severity === "HIGH")).length;
  const ackAll = () => {
    for (const a of filteredAlerts) if (!a.acknowledged) getRuntimeAdapter().sendCommand({ kind: "alert.acknowledge", id: a.id });
  };

  const filteredEvents = useMemo(() => {
    const q = query.trim().toLowerCase();
    return snap.events.filter((e) => {
      if (logSeverity !== "ALL" && e.severity !== logSeverity) return false;
      if (q && !(e.message.toLowerCase().includes(q) || e.component.toLowerCase().includes(q) || e.source.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [snap.events, logSeverity, query]);

  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
      {/* Header + severity summary strip */}
      <Panel bodyClassName="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-panel-border px-4 py-3">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Incident Console</div>
            <h1 className="mt-0.5 text-[15px] font-semibold leading-tight">Events &amp; Alerts</h1>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1 text-[11px]">
              <span className={cn("h-1.5 w-1.5 rounded-full", unresolvedCrit > 0 ? "bg-status-crit animate-pulse" : "bg-status-ok")} />
              <span className="text-muted-foreground">Unresolved:</span>
              <span className="num font-semibold">{unresolvedCrit}</span>
            </div>
            <button
              onClick={ackAll}
              disabled={filteredAlerts.every((a) => a.acknowledged)}
              className="inline-flex items-center gap-1.5 rounded-sm border border-panel-border bg-panel-elevated px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
            >
              <CheckCheck className="h-3.5 w-3.5" /> Ack visible
            </button>
          </div>
        </div>

        {/* Severity summary — 5 cells with hairline dividers */}
        <div className="grid grid-cols-2 gap-px bg-panel-border sm:grid-cols-5">
          {(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const).map((s) => {
            const active = severityFilter === s;
            return (
              <button
                key={s}
                onClick={() => setSeverityFilter(active ? "ALL" : s)}
                className={cn(
                  "group flex items-center justify-between bg-panel px-3 py-2.5 text-left transition-colors hover:bg-panel-elevated",
                  active && "bg-panel-elevated ring-1 ring-inset ring-primary/40",
                )}
              >
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{s}</div>
                  <div className={cn(
                    "num mt-0.5 text-xl font-bold leading-none",
                    s === "CRITICAL" && "text-status-crit",
                    s === "HIGH" && "text-status-crit/90",
                    s === "MEDIUM" && "text-status-warn",
                    s === "LOW" && "text-status-info",
                    s === "INFO" && "text-foreground/70",
                  )}>
                    {String(counts[s]).padStart(2, "0")}
                  </div>
                </div>
                <span className={cn("h-8 w-0.5 rounded-full opacity-70", sevAccent[s])} />
              </button>
            );
          })}
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2 border-t border-panel-border bg-panel-elevated/50 px-3 py-2">
          <div className="flex items-center gap-1 rounded-sm border border-panel-border bg-panel px-2 py-1">
            <Search className="h-3 w-3 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter title, message, subsystem…"
              className="w-56 bg-transparent text-[11.5px] outline-none placeholder:text-muted-foreground/60"
            />
            {query && (
              <button onClick={() => setQuery("")} className="text-muted-foreground hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <div className="mx-1 h-4 w-px bg-panel-border" />
          {/* Tab switch */}
          <div className="flex overflow-hidden rounded-sm border border-panel-border">
            {(["alerts", "events", "incidents", "live"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "px-2.5 py-1 text-[10.5px] font-medium uppercase tracking-wider transition-colors",
                  tab === t ? "bg-primary/15 text-primary" : "bg-panel text-muted-foreground hover:bg-muted",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "alerts" && (
            <>
              <div className="mx-1 h-4 w-px bg-panel-border" />
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Source</span>
                <button
                  onClick={() => setSourceFilter("ALL")}
                  className={cn(
                    "rounded-sm border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wider",
                    sourceFilter === "ALL" ? "border-primary/40 bg-primary/10 text-primary" : "border-panel-border bg-panel text-muted-foreground hover:bg-muted",
                  )}
                >
                  All
                </button>
                {sources.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSourceFilter(s)}
                    className={cn(
                      "rounded-sm border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wider",
                      sourceFilter === s ? "border-primary/40 bg-primary/10 text-primary" : "border-panel-border bg-panel text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[10.5px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={showAckd}
                  onChange={(e) => setShowAckd(e.target.checked)}
                  className="h-3 w-3 accent-primary"
                />
                Show acknowledged
              </label>
            </>
          )}

          {tab === "events" && (
            <>
              <div className="mx-1 h-4 w-px bg-panel-border" />
              <div className="flex flex-wrap items-center gap-1">
                {(["ALL", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setLogSeverity(s)}
                    className={cn(
                      "rounded-sm border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wider",
                      logSeverity === s ? "border-primary/40 bg-primary/10 text-primary" : "border-panel-border bg-panel text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </Panel>

      {tab === "alerts" && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_420px]">
          {/* Feed */}
          <Panel bodyClassName="p-0">
            {filteredAlerts.length === 0 ? (
              <EmptyState title="No alerts match filters" description="Adjust severity, source, or search to see more." />
            ) : (
              <div className="max-h-[70vh] overflow-y-auto">
                {grouped.map(([day, list]) => (
                  <div key={day}>
                    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-panel-border bg-panel-elevated/95 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground backdrop-blur">
                      <span>{day}</span>
                      <span className="num">{list.length} events</span>
                    </div>
                    <ul>
                      {list.map((a) => {
                        const active = selected?.id === a.id;
                        return (
                          <li key={a.id}>
                            <button
                              onClick={() => setSelectedId(a.id)}
                              className={cn(
                                "flex w-full border-b border-panel-border/60 text-left transition-colors",
                                active ? "bg-primary/5" : "hover:bg-muted/40",
                                a.acknowledged && "opacity-60",
                              )}
                            >
                              <div className={cn("w-1 shrink-0", sevAccent[a.severity])} />
                              <div className="min-w-0 flex-1 px-3 py-2.5">
                                <div className="flex items-center gap-2">
                                  <span className="num text-[10.5px] text-muted-foreground">{fmtTime(a.createdAt)}</span>
                                  <StatusBadge tone={sevTone(a.severity)} size="sm" dot={false} uppercase>
                                    {a.severity}
                                  </StatusBadge>
                                  <span className="num text-[10px] uppercase tracking-wider text-muted-foreground">
                                    {a.source}
                                  </span>
                                  {a.acknowledged && (
                                    <span className="ml-1 text-[9.5px] font-semibold uppercase tracking-widest text-status-ok/80">
                                      ✓ Ack
                                    </span>
                                  )}
                                  <span className="ml-auto num text-[10px] text-muted-foreground/70">
                                    #{a.id.slice(-6).toUpperCase()}
                                  </span>
                                </div>
                                <div className="mt-1 truncate text-[12.5px] font-semibold text-foreground">{a.title}</div>
                                <div className="mt-0.5 line-clamp-1 text-[11.5px] text-muted-foreground">{a.description}</div>
                              </div>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {/* Detail rail */}
          <Panel bodyClassName="p-0">
            {selected ? (
              <div className="flex max-h-[70vh] flex-col">
                <div className="flex items-start gap-3 border-b border-panel-border px-4 py-3">
                  <div className={cn("mt-1 h-8 w-1 shrink-0 rounded-full", sevAccent[selected.severity])} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone={sevTone(selected.severity)} size="sm">{selected.severity}</StatusBadge>
                      <span className="num text-[10px] uppercase tracking-wider text-muted-foreground">{selected.source}</span>
                      <span className="num ml-auto text-[10px] text-muted-foreground/70">#{selected.id.slice(-6).toUpperCase()}</span>
                    </div>
                    <h3 className="mt-1.5 text-[13.5px] font-semibold leading-snug">{selected.title}</h3>
                    <div className="num mt-0.5 text-[10.5px] text-muted-foreground">
                      {fmtTime(selected.createdAt)} · {relativeTime(selected.createdAt)}
                    </div>
                  </div>
                </div>

                <div className="flex-1 space-y-3 overflow-y-auto p-4 text-[12px] leading-relaxed">
                  <section>
                    <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Description</div>
                    <p className="mt-1 text-foreground/90">{selected.description}</p>
                  </section>
                  <section>
                    <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Suggested action</div>
                    <p className="mt-1 rounded-sm border border-panel-border bg-panel-elevated px-2.5 py-1.5">{selected.suggestedAction}</p>
                  </section>
                  <section>
                    <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Metadata</div>
                    <dl className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1 text-[11px]">
                      <dt className="text-muted-foreground">Source</dt>
                      <dd className="col-span-2 num">{selected.source}</dd>
                      <dt className="text-muted-foreground">Incident</dt>
                      <dd className="col-span-2 num">{selected.incidentId ?? "—"}</dd>
                      <dt className="text-muted-foreground">Status</dt>
                      <dd className="col-span-2">{selected.acknowledged ? "Acknowledged" : "Open"}</dd>
                    </dl>
                  </section>
                </div>

                <div className="flex items-center gap-2 border-t border-panel-border bg-panel-elevated/60 px-3 py-2">
                  {!selected.acknowledged ? (
                    <CommandButton
                      kind="alert.acknowledge"
                      label="Acknowledge"
                      icon={<CheckCheck className="h-3.5 w-3.5" />}
                      targetId={selected.id}
                      skipConfirmation
                      variant="primary"
                    />
                  ) : (
                    <span className="text-[11px] font-semibold uppercase tracking-widest text-status-ok/90">✓ Acknowledged</span>
                  )}
                  <span className="ml-auto text-[10px] text-muted-foreground">Runtime authoritative · UI request only</span>
                </div>

              </div>
            ) : (
              <EmptyState title="No alert selected" description="Pick an alert from the feed to inspect details." />
            )}
          </Panel>
        </div>
      )}

      {tab === "events" && (
        <Panel bodyClassName="p-0">
          <div className="max-h-[70vh] overflow-auto">
            <table className="w-full min-w-[820px] text-[11.5px]">
              <thead className="sticky top-0 z-10 border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground backdrop-blur">
                <tr>
                  <th className="w-28 px-2 py-1.5 text-left">Time</th>
                  <th className="w-24 px-2 py-1.5 text-left">Level</th>
                  <th className="w-40 px-2 py-1.5 text-left">Component</th>
                  <th className="px-2 py-1.5 text-left">Message</th>
                  <th className="w-32 px-2 py-1.5 text-left">Correlation</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((e) => (
                  <tr key={e.id} className="border-b border-panel-border/60 hover:bg-muted/40">
                    <td className="num px-2 py-1 text-muted-foreground">{fmtTime(e.at)}</td>
                    <td className="px-2 py-1">
                      <StatusBadge tone={logTone(e.severity)} size="sm">{e.severity}</StatusBadge>
                    </td>
                    <td className="num px-2 py-1 text-muted-foreground">{e.component}</td>
                    <td className="px-2 py-1">{e.message}</td>
                    <td className="num px-2 py-1 text-muted-foreground">{e.correlationId ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {tab === "incidents" && (
        <Panel bodyClassName="p-0">
          {snap.incidents.length === 0 ? (
            <EmptyState title="No incidents" description="No incidents recorded in the current session." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-[11.5px]">
                <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 text-left">Severity</th>
                    <th className="px-2 py-1.5 text-left">Status</th>
                    <th className="px-2 py-1.5 text-left">Title</th>
                    <th className="px-2 py-1.5 text-left">Impact</th>
                    <th className="px-2 py-1.5 text-left">Components</th>
                    <th className="px-2 py-1.5 text-left">Started</th>
                    <th className="px-2 py-1.5 text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {snap.incidents.map((i) => (
                    <tr key={i.id} className="border-b border-panel-border/60">
                      <td className="px-3 py-1.5">
                        <StatusBadge tone={sevTone(i.severity)} size="sm">{i.severity}</StatusBadge>
                      </td>
                      <td className="px-2 py-1.5">
                        <StatusBadge tone={i.status === "RESOLVED" ? "ok" : i.status === "MITIGATED" ? "info" : "warn"} size="sm">
                          {i.status}
                        </StatusBadge>
                      </td>
                      <td className="px-2 py-1.5 font-medium">{i.title}</td>
                      <td className="px-2 py-1.5 text-muted-foreground">{i.impact}</td>
                      <td className="num px-2 py-1.5 text-muted-foreground">{i.affectedComponents.join(", ")}</td>
                      <td className="num px-2 py-1.5 text-muted-foreground">{relativeTime(i.startedAt)}</td>
                      <td className="px-2 py-1.5 text-right">
                        {i.status !== "RESOLVED" && (
                          <CommandButton
                            kind="incident.acknowledge"
                            label="Ack"
                            targetId={i.id}
                            skipConfirmation
                            variant="outline"
                          />
                        )}
                      </td>
                    </tr>
                  ))}

                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      {tab === "live" && (
        <Panel bodyClassName="p-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-panel-border bg-panel-elevated/60 px-3 py-2">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Router live tail
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {(["ALL", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setLiveSevFilter(s as "ALL" | EventSeverity)}
                  className={cn(
                    "rounded-sm border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wider",
                    liveSevFilter === s
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-panel-border bg-panel text-muted-foreground hover:bg-muted",
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {livePauseState.paused && livePauseState.pending > 0 && (
                <span className="num text-[10.5px] text-status-warn">
                  +{livePauseState.pending} buffered
                </span>
              )}
              <button
                onClick={() => eventHistoryStore.setPaused(!livePauseState.paused)}
                className="inline-flex items-center gap-1.5 rounded-sm border border-panel-border bg-panel px-2 py-1 text-[10.5px] font-medium uppercase tracking-wider hover:bg-muted"
              >
                {livePauseState.paused ? (
                  <><Play className="h-3 w-3" /> Resume</>
                ) : (
                  <><Pause className="h-3 w-3" /> Pause</>
                )}
              </button>
              <button
                onClick={() => eventHistoryStore.clear()}
                className="inline-flex items-center gap-1.5 rounded-sm border border-panel-border bg-panel px-2 py-1 text-[10.5px] font-medium uppercase tracking-wider hover:bg-muted"
              >
                <Trash2 className="h-3 w-3" /> Clear
              </button>
            </div>
          </div>
          <LiveEventsVirtualList
            events={liveEvents}
            severityFilter={liveSevFilter}
          />
        </Panel>
      )}
    </div>
  );
}

const ROW_HEIGHT = 30;

function LiveEventsVirtualList({
  events,
  severityFilter,
}: {
  events: ReturnType<typeof useEventHistory>;
  severityFilter: "ALL" | EventSeverity;
}) {
  const filtered = useMemo(
    () =>
      severityFilter === "ALL"
        ? events
        : events.filter((e) => e.severity === severityFilter),
    [events, severityFilter],
  );

  const parentRef = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  if (filtered.length === 0) {
    return (
      <EmptyState
        title="No routed events yet"
        description="Envelopes emitted by the runtime adapter or fixture source will appear here in real time."
      />
    );
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div className="rounded-sm border border-panel-border">
      <div className="grid grid-cols-[96px_96px_1fr_112px_2fr_64px] gap-0 border-b border-panel-border bg-panel-elevated px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
        <div>Time</div>
        <div>Severity</div>
        <div>Type</div>
        <div>Source</div>
        <div>Correlation / IDs</div>
        <div className="text-right">Seq</div>
      </div>
      <div ref={parentRef} className="max-h-[70vh] overflow-auto">
        <div
          style={{ height: virtualizer.getTotalSize(), position: "relative", minWidth: 900 }}
        >
          {items.map((v) => {
            const e = filtered[v.index];
            return (
              <div
                key={e.eventId}
                className="grid grid-cols-[96px_96px_1fr_112px_2fr_64px] items-center gap-0 border-b border-panel-border/60 px-2 text-[11.5px] hover:bg-muted/40"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  right: 0,
                  transform: `translateY(${v.start}px)`,
                  height: v.size,
                }}
              >
                <div className="num text-muted-foreground">
                  {fmtTime(e.receivedAt ?? e.emittedAt)}
                </div>
                <div>
                  <StatusBadge
                    tone={
                      e.severity === "CRITICAL" || e.severity === "ERROR"
                        ? "crit"
                        : e.severity === "WARNING"
                          ? "warn"
                          : e.severity === "INFO"
                            ? "info"
                            : "neutral"
                    }
                    size="sm"
                  >
                    {e.severity}
                  </StatusBadge>
                </div>
                <div className="num truncate">{e.type}</div>
                <div className="num text-muted-foreground">
                  {e.source === "DEVELOPMENT_FIXTURE" ? "FIXTURE" : "RUNTIME"}
                </div>
                <div className="num truncate text-muted-foreground">
                  {[e.correlationId, e.commandId, e.orderId, e.positionId, e.incidentId, e.reconciliationRunId]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
                <div className="num text-right text-muted-foreground">{e.sequence}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
