// Notification Center — persistent drawer showing all routed events that
// qualified for persistence, with filters, ack, and clear actions.

import { useMemo, useState } from "react";
import { Bell, Check, CheckCheck, Trash2, X, AlertTriangle, Info, ShieldAlert } from "lucide-react";
import {
  notificationCenter,
  useNotifications,
  useNotificationCounts,
} from "@/lib/runtime/events/notification-center";
import type { EventSeverity, RuntimeEventEnvelope } from "@/lib/runtime/events/event-types";
import { relativeTime } from "@/lib/format";

type Filter = "unread" | "critical" | "fixture" | "all";

const severityColor: Record<EventSeverity, string> = {
  TRACE: "text-muted-foreground",
  DEBUG: "text-muted-foreground",
  INFO: "text-status-ok",
  WARNING: "text-status-warn",
  ERROR: "text-status-crit",
  CRITICAL: "text-status-crit",
};

function severityIcon(sev: EventSeverity) {
  if (sev === "CRITICAL" || sev === "ERROR") return <ShieldAlert className="h-3.5 w-3.5" />;
  if (sev === "WARNING") return <AlertTriangle className="h-3.5 w-3.5" />;
  return <Info className="h-3.5 w-3.5" />;
}

function extractMessage(env: RuntimeEventEnvelope): string {
  const p = env.payload as Record<string, unknown> | undefined;
  if (p && typeof p === "object") {
    for (const k of ["reason", "message", "note", "state", "status"]) {
      const v = p[k];
      if (typeof v === "string" && v.length) return v;
    }
  }
  return env.type.replaceAll(".", " · ");
}

export function NotificationCenterButton() {
  const [open, setOpen] = useState(false);
  const counts = useNotificationCounts();
  const badge = counts.unread;
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="relative grid h-8 w-8 place-items-center rounded-md border border-panel-border bg-panel-elevated hover:bg-muted"
        aria-label="Notifications"
      >
        <Bell className="h-3.5 w-3.5" />
        {badge > 0 && (
          <span
            className={`absolute -right-1 -top-1 min-w-[16px] rounded-full px-1 text-[9px] font-semibold text-primary-foreground ${
              counts.critical > 0 ? "bg-status-crit" : "bg-status-warn"
            }`}
          >
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </button>
      {open && <NotificationCenterDrawer onClose={() => setOpen(false)} />}
    </>
  );
}

function NotificationCenterDrawer({ onClose }: { onClose: () => void }) {
  const [filter, setFilter] = useState<Filter>("unread");
  const all = useNotifications();
  const counts = useNotificationCounts();

  const list = useMemo(() => {
    switch (filter) {
      case "unread":
        return all.filter((n) => !n.acknowledged);
      case "critical":
        return all.filter((n) => n.decision.priority === "CRITICAL" || n.latest.severity === "CRITICAL");
      case "fixture":
        return all.filter((n) => n.latest.source === "DEVELOPMENT_FIXTURE");
      default:
        return all;
    }
  }, [all, filter]);

  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-label="Notification center">
      <div className="flex-1 bg-black/60 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="flex h-full w-full max-w-md flex-col border-l border-panel-border bg-background shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-panel-border px-3 py-2">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Notification Center</div>
            <div className="text-sm font-semibold">
              {counts.unread} unread{" "}
              <span className="text-[11px] text-muted-foreground">
                · {counts.total} total · {counts.critical} critical
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="grid h-8 w-8 place-items-center rounded-md border border-panel-border bg-panel-elevated hover:bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-1 border-b border-panel-border px-2 py-1.5 overflow-x-auto scrollbar-none">
          {(
            [
              ["unread", `Unread (${counts.unread})`],
              ["critical", `Critical (${counts.critical})`],
              ["fixture", `Fixture (${counts.fixture})`],
              ["all", `All (${counts.total})`],
            ] as Array<[Filter, string]>
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={`shrink-0 rounded-sm px-2 py-1 text-[11px] ${
                filter === k
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {label}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => notificationCenter.acknowledgeAll()}
              className="inline-flex items-center gap-1 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1 text-[11px] hover:bg-muted"
              disabled={counts.unread === 0}
            >
              <CheckCheck className="h-3 w-3" /> Ack all
            </button>
            <button
              onClick={() => notificationCenter.clear()}
              className="inline-flex items-center gap-1 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1 text-[11px] hover:bg-muted"
              disabled={counts.total === 0}
            >
              <Trash2 className="h-3 w-3" /> Clear
            </button>
          </div>
        </div>

        {/* List */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {list.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              No notifications match this filter.
            </div>
          ) : (
            <ul className="divide-y divide-panel-border">
              {list.map((n) => {
                const env = n.latest;
                const color = severityColor[env.severity];
                return (
                  <li
                    key={n.id}
                    className={`flex items-start gap-2 px-3 py-2 ${
                      n.acknowledged ? "opacity-70" : ""
                    } ${n.decision.priority === "CRITICAL" ? "bg-status-crit/[0.05]" : ""}`}
                  >
                    <span className={`mt-0.5 shrink-0 ${color}`}>{severityIcon(env.severity)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[12px] font-medium">{env.type}</span>
                        <span
                          className={`shrink-0 rounded-sm px-1 text-[9px] font-semibold uppercase tracking-wider ${color}`}
                        >
                          {env.severity}
                        </span>
                        {env.source === "DEVELOPMENT_FIXTURE" && (
                          <span className="shrink-0 rounded-sm bg-status-warn/15 px-1 text-[9px] font-semibold uppercase tracking-wider text-status-warn">
                            Fixture
                          </span>
                        )}
                        {n.count > 1 && (
                          <span className="shrink-0 rounded-sm bg-muted px-1 text-[9px] font-semibold text-muted-foreground">
                            ×{n.count}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                        {extractMessage(env)}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground/80">
                        <span className="num">{relativeTime(n.lastSeenAt)}</span>
                        <span>·</span>
                        <span className="num">seq {env.sequence}</span>
                        {env.commandId && (
                          <>
                            <span>·</span>
                            <span className="num truncate">cmd {env.commandId.slice(-6)}</span>
                          </>
                        )}
                      </div>
                    </div>
                    {!n.acknowledged && (
                      <button
                        onClick={() => notificationCenter.acknowledge(n.id)}
                        className="grid h-6 w-6 shrink-0 place-items-center rounded-sm border border-panel-border bg-panel-elevated hover:bg-muted"
                        aria-label="Acknowledge"
                        title="Acknowledge"
                      >
                        <Check className="h-3 w-3" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t border-panel-border px-3 py-1.5 text-[10px] text-muted-foreground">
          Notifications are frontend-derived. Authoritative state lives in the runtime and broker.
        </div>
      </aside>
    </div>
  );
}
