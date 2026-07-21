import { useEffect, useState } from "react";
import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Clock,
  HelpCircle,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCommandCounts, useCommandStore, type RuntimeCommandStatus } from "@/lib/runtime";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { relativeTime } from "@/lib/format";

const stateTone: Record<RuntimeCommandStatus["state"], StatusTone> = {
  PREPARED: "neutral",
  SUBMITTING: "info",
  ACCEPTED: "info",
  ACKNOWLEDGED: "info",
  IN_PROGRESS: "info",
  COMPLETED: "ok",
  FAILED: "crit",
  TIMED_OUT: "crit",
  EXECUTION_UNKNOWN: "crit",
  CANCELLED: "neutral",
};

const stateLabel: Record<RuntimeCommandStatus["state"], string> = {
  PREPARED: "Prepared",
  SUBMITTING: "Submitting",
  ACCEPTED: "Accepted",
  ACKNOWLEDGED: "Acknowledged",
  IN_PROGRESS: "In progress",
  COMPLETED: "Completed",
  FAILED: "Failed",
  TIMED_OUT: "Timed out",
  EXECUTION_UNKNOWN: "Execution unknown",
  CANCELLED: "Cancelled",
};

type Filter = "active" | "unknown" | "failed" | "completed" | "all";

export function CommandCenterButton() {
  const [open, setOpen] = useState(false);
  const counts = useCommandCounts();

  const alertTone =
    counts.unknown > 0
      ? "crit"
      : counts.failed > 0
        ? "crit"
        : counts.active > 0
          ? "info"
          : "neutral";
  const total = counts.active + counts.failed + counts.unknown;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="relative inline-flex h-8 items-center gap-1.5 rounded-md border border-panel-border bg-panel-elevated px-2 text-[11px] hover:bg-muted"
        aria-label="Command center"
        title="Command activity"
      >
        <Activity className="h-3.5 w-3.5" />
        <span className="hidden sm:inline num">{counts.active}</span>
        {total > 0 && (
          <span
            className={cn(
              "absolute -right-1 -top-1 min-w-[16px] rounded-full px-1 text-[9px] font-semibold text-primary-foreground",
              alertTone === "crit" ? "bg-status-crit" : "bg-status-info",
            )}
          >
            {total}
          </span>
        )}
      </button>
      <CommandDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function CommandDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const commands = useCommandStore();
  const counts = useCommandCounts();
  const [filter, setFilter] = useState<Filter>("active");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  const filtered = commands.filter((c) => {
    if (filter === "all") return true;
    if (filter === "active")
      return (
        c.state === "SUBMITTING" ||
        c.state === "ACCEPTED" ||
        c.state === "ACKNOWLEDGED" ||
        c.state === "IN_PROGRESS" ||
        c.state === "PREPARED"
      );
    if (filter === "unknown") return c.state === "EXECUTION_UNKNOWN";
    if (filter === "failed") return c.state === "FAILED" || c.state === "TIMED_OUT";
    if (filter === "completed") return c.state === "COMPLETED";
    return true;
  });

  const active = selected ? (commands.find((c) => c.commandId === selected) ?? null) : null;

  return (
    <div
      className={cn(
        "fixed inset-0 z-[60] transition-opacity",
        open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
      aria-hidden={!open}
    >
      <div className="absolute inset-0 bg-background/70 backdrop-blur-sm" onClick={onClose} />
      <aside
        role="dialog"
        aria-label="Command center"
        className={cn(
          "absolute inset-y-0 right-0 flex w-full max-w-[520px] flex-col border-l border-panel-border bg-sidebar shadow-2xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="flex items-center gap-2 border-b border-panel-border px-3 py-3">
          <Activity className="h-4 w-4 text-primary" />
          <div className="min-w-0 flex-1">
            <div className="text-[12.5px] font-semibold">Command Center</div>
            <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
              Runtime request activity
            </div>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-md border border-panel-border bg-panel-elevated text-muted-foreground active:bg-muted"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex items-center gap-1 border-b border-panel-border/70 px-2 py-1.5 text-[10.5px]">
          <FilterChip
            label={`Active ${counts.active}`}
            tone="info"
            active={filter === "active"}
            onClick={() => setFilter("active")}
          />
          <FilterChip
            label={`Unknown ${counts.unknown}`}
            tone="crit"
            active={filter === "unknown"}
            onClick={() => setFilter("unknown")}
          />
          <FilterChip
            label={`Failed ${counts.failed}`}
            tone="crit"
            active={filter === "failed"}
            onClick={() => setFilter("failed")}
          />
          <FilterChip
            label={`Done ${counts.completed}`}
            tone="ok"
            active={filter === "completed"}
            onClick={() => setFilter("completed")}
          />
          <FilterChip
            label="All"
            tone="neutral"
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
        </div>

        <div className="flex min-h-0 flex-1">
          <ul className="w-1/2 min-w-0 divide-y divide-panel-border/60 overflow-y-auto border-r border-panel-border/60">
            {filtered.length === 0 && (
              <li className="p-6 text-center text-[11.5px] text-muted-foreground">
                No commands in this view.
              </li>
            )}
            {filtered.map((c) => (
              <li key={c.commandId}>
                <button
                  onClick={() => setSelected(c.commandId)}
                  className={cn(
                    "w-full px-3 py-2 text-left text-[11.5px] hover:bg-muted/50",
                    active?.commandId === c.commandId && "bg-primary/10",
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <StateIcon state={c.state} />
                    <span className="truncate font-medium">{c.kind}</span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-2 text-[10.5px] text-muted-foreground">
                    <span className="truncate">{c.targetId ?? "—"}</span>
                    <StatusBadge tone={stateTone[c.state]} size="sm">
                      {stateLabel[c.state]}
                    </StatusBadge>
                  </div>
                  {c.currentStep && (
                    <div className="mt-0.5 truncate text-[10.5px] text-muted-foreground">
                      {c.currentStep}
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>

          <div className="min-w-0 flex-1 overflow-y-auto">
            {active ? (
              <CommandDetail cmd={active} />
            ) : (
              <div className="grid h-full place-items-center p-6 text-center text-[11.5px] text-muted-foreground">
                Select a command to inspect its lifecycle.
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

function FilterChip({
  label,
  tone,
  active,
  onClick,
}: {
  label: string;
  tone: StatusTone;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-sm border px-2 py-1 uppercase tracking-wider",
        active
          ? "border-primary/60 bg-primary/15 text-foreground"
          : "border-panel-border bg-panel-elevated text-muted-foreground hover:text-foreground",
      )}
    >
      <span className={cn(tone === "crit" && active && "text-status-crit")}>{label}</span>
    </button>
  );
}

function StateIcon({ state }: { state: RuntimeCommandStatus["state"] }) {
  if (state === "COMPLETED") return <CheckCircle2 className="h-3.5 w-3.5 text-status-ok" />;
  if (state === "FAILED" || state === "TIMED_OUT")
    return <XCircle className="h-3.5 w-3.5 text-status-crit" />;
  if (state === "EXECUTION_UNKNOWN") return <HelpCircle className="h-3.5 w-3.5 text-status-crit" />;
  if (state === "CANCELLED") return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
  return <Loader2 className="h-3.5 w-3.5 animate-spin text-status-info" />;
}

function CommandDetail({ cmd }: { cmd: RuntimeCommandStatus }) {
  return (
    <div className="space-y-3 p-3 text-[11.5px]">
      <div>
        <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">Command</div>
        <div className="mt-0.5 font-semibold">{cmd.kind}</div>
        <div className="mt-1">
          <StatusBadge tone={stateTone[cmd.state]} size="sm">
            {stateLabel[cmd.state]}
          </StatusBadge>
        </div>
      </div>

      {cmd.state === "EXECUTION_UNKNOWN" && (
        <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-2 text-[11px] text-status-crit">
          <div className="flex items-center gap-1.5 font-semibold">
            <AlertOctagon className="h-3.5 w-3.5" /> Execution result is unknown
          </div>
          <p className="mt-1 text-status-crit/90">
            The broker may have accepted or completed this operation. Do not retry until
            reconciliation confirms the actual broker state.
          </p>
        </div>
      )}

      {cmd.currentStep && (
        <div>
          <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
            Current step
          </div>
          <div>{cmd.currentStep}</div>
        </div>
      )}

      {cmd.reason && (
        <div>
          <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
            Operator reason
          </div>
          <div>{cmd.reason}</div>
        </div>
      )}

      {cmd.errorMessage && (
        <div>
          <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">Error</div>
          <div className="text-status-crit">{cmd.errorMessage}</div>
          {cmd.errorCode && (
            <div className="num text-[10.5px] text-muted-foreground">{cmd.errorCode}</div>
          )}
        </div>
      )}

      <dl className="grid grid-cols-[100px_1fr] gap-y-1 border-t border-panel-border pt-2 text-[10.5px]">
        <MetaRow k="Command ID" v={cmd.commandId} />
        <MetaRow k="Client Req ID" v={cmd.clientRequestId} />
        <MetaRow k="Correlation" v={cmd.correlationId} />
        <MetaRow k="Idempotency" v={cmd.idempotencyKey} />
        {cmd.targetId && <MetaRow k="Target" v={cmd.targetId} />}
        <MetaRow k="Created" v={relativeTime(cmd.createdAt)} />
        <MetaRow k="Updated" v={relativeTime(cmd.updatedAt)} />
        {cmd.completedAt && <MetaRow k="Completed" v={relativeTime(cmd.completedAt)} />}
      </dl>
    </div>
  );
}

function MetaRow({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="num truncate">{v}</dd>
    </>
  );
}
