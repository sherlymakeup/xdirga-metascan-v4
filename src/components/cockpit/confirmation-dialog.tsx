import { useEffect, useState } from "react";
import { AlertOctagon, Loader2, Minimize2, ShieldAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import type { RuntimeCommandStatus } from "@/lib/runtime";

export type DangerLevel = 1 | 2 | 3 | 4;

/**
 * Result contract for `onConfirm`. When the caller returns `{ accepted:false }`
 * the dialog stays open and surfaces `blockedReason`. When accepted, the dialog
 * remains open following the live `commandStatus` prop until a terminal state
 * is reached (or the operator minimizes).
 */
export interface ConfirmationSubmitResult {
  accepted: boolean;
  blockedReason?: string;
  commandId?: string;
  correlationId?: string;
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  level: DangerLevel;
  title: string;
  description: ReactNode;
  impactSummary?: ReactNode;
  confirmPhrase?: string;
  confirmLabel?: string;
  requireReason?: boolean;
  reasonPlaceholder?: string;
  onConfirm: (
    reason: string,
  ) => Promise<ConfirmationSubmitResult | void> | ConfirmationSubmitResult | void;
  destructive?: boolean;
  /** Live command status for the in-flight submission (post-accept). */
  commandStatus?: RuntimeCommandStatus | null;
}

const TERMINAL: RuntimeCommandStatus["state"][] = [
  "COMPLETED",
  "FAILED",
  "TIMED_OUT",
  "EXECUTION_UNKNOWN",
  "CANCELLED",
];

export function ConfirmationDialog({
  open,
  onOpenChange,
  level,
  title,
  description,
  impactSummary,
  confirmPhrase,
  confirmLabel = "Confirm",
  requireReason = false,
  reasonPlaceholder = "Operator reason (audit log)",
  onConfirm,
  destructive = false,
  commandStatus,
}: Props) {
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [phase, setPhase] = useState<"review" | "submitting" | "inflight" | "terminal">("review");
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const [correlationId, setCorrelationId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const needsPhrase = level >= 3 && !!confirmPhrase;
  const needsReason = level >= 3 || requireReason;
  const phraseOk = !needsPhrase || typed.trim() === confirmPhrase;
  const reasonOk = !needsReason || reason.trim().length >= 4;
  const canConfirm = phraseOk && reasonOk && phase === "review";

  // Follow the live command status through to a terminal state.
  useEffect(() => {
    if (!commandStatus) return;
    if (TERMINAL.includes(commandStatus.state)) setPhase("terminal");
    else if (phase !== "inflight") setPhase("inflight");
  }, [commandStatus, phase]);

  const reset = () => {
    setTyped("");
    setReason("");
    setPhase("review");
    setBlockedReason(null);
    setCorrelationId(null);
    setLocalError(null);
  };

  const closeIfSafe = (open: boolean) => {
    if (!open) {
      // Never block close after terminal; block only during synchronous submit.
      if (phase === "submitting") return;
      reset();
    }
    onOpenChange(open);
  };

  const submit = async () => {
    setPhase("submitting");
    setBlockedReason(null);
    setLocalError(null);
    try {
      const result = await Promise.resolve(onConfirm(reason.trim()));
      if (result && result.accepted === false) {
        setBlockedReason(result.blockedReason ?? "Command was blocked.");
        setPhase("review");
        return;
      }
      if (result && result.correlationId) setCorrelationId(result.correlationId);
      setPhase("inflight");
    } catch (e) {
      setLocalError((e as Error)?.message ?? "Command failed");
      setPhase("review");
    }
  };

  const minimize = () => {
    // Keep command running; just close the dialog.
    onOpenChange(false);
  };

  const terminalState = commandStatus?.state;
  const terminalTone =
    terminalState === "COMPLETED"
      ? "ok"
      : terminalState === "EXECUTION_UNKNOWN"
        ? "unknown"
        : terminalState
          ? "fail"
          : "ok";

  return (
    <Dialog open={open} onOpenChange={closeIfSafe}>
      <DialogContent className="max-w-lg border-panel-border bg-panel p-0">
        <DialogHeader className="border-b border-panel-border p-4">
          <DialogTitle
            className={cn(
              "flex items-center gap-2 text-sm font-semibold uppercase tracking-wide",
              destructive && "text-status-crit",
            )}
          >
            {destructive ? (
              <AlertOctagon className="h-4 w-4" />
            ) : (
              <ShieldAlert className="h-4 w-4" />
            )}
            {title}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            {description}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 p-4">
          {impactSummary && (
            <div className="rounded-sm border border-panel-border bg-panel-elevated p-3 text-xs">
              <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
                Impact
              </div>
              {impactSummary}
            </div>
          )}

          {level === 4 && (
            <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-2.5 text-[11.5px] text-status-crit">
              <strong>Irreversible action.</strong> This will affect live runtime state. An audit
              event will be created.
            </div>
          )}

          {phase === "review" && needsPhrase && (
            <div className="space-y-1.5">
              <Label className="text-xs">
                Type <span className="num text-foreground">{confirmPhrase}</span> to confirm
              </Label>
              <Input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                className="num h-8 bg-background text-sm"
                placeholder={confirmPhrase}
              />
            </div>
          )}

          {phase === "review" && needsReason && (
            <div className="space-y-1.5">
              <Label className="text-xs">Operator reason</Label>
              <Textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                className="bg-background text-sm"
                placeholder={reasonPlaceholder}
              />
            </div>
          )}

          {blockedReason && (
            <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-2.5 text-[11.5px] text-status-crit">
              <strong>Blocked.</strong> {blockedReason}
            </div>
          )}
          {localError && (
            <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-2.5 text-[11.5px] text-status-crit">
              {localError}
            </div>
          )}

          {(phase === "inflight" || phase === "terminal") && (
            <div className="rounded-sm border border-panel-border bg-background p-3 text-xs">
              <LifecycleProgress status={commandStatus ?? null} />
              {(commandStatus?.correlationId ?? correlationId) && (
                <div className="mt-2 border-t border-panel-border pt-2 num text-[10.5px] text-muted-foreground">
                  correlationId: {commandStatus?.correlationId ?? correlationId}
                </div>
              )}
              {commandStatus?.state === "EXECUTION_UNKNOWN" && (
                <div className="mt-2 rounded-sm border border-status-warn/40 bg-status-warn/10 p-2 text-[11px] text-status-warn">
                  Broker execution is undetermined. Retries are locked on this entity until
                  reconciliation resolves the outcome.
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 border-t border-panel-border p-3">
          {phase === "review" && (
            <>
              <button
                onClick={() => closeIfSafe(false)}
                className="rounded-sm border border-panel-border bg-panel-elevated px-3 py-1.5 text-xs hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={!canConfirm}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-xs font-semibold uppercase tracking-wider disabled:opacity-40",
                  destructive
                    ? "bg-status-crit text-primary-foreground hover:bg-status-crit/90"
                    : "bg-primary text-primary-foreground hover:bg-primary/90",
                )}
              >
                {confirmLabel}
              </button>
            </>
          )}
          {phase === "submitting" && (
            <button
              disabled
              className="inline-flex items-center gap-1.5 rounded-sm bg-panel-elevated px-3 py-1.5 text-xs uppercase tracking-wider opacity-70"
            >
              <Loader2 className="h-3 w-3 animate-spin" />
              Submitting
            </button>
          )}
          {phase === "inflight" && (
            <button
              onClick={minimize}
              className="inline-flex items-center gap-1.5 rounded-sm border border-panel-border bg-panel-elevated px-3 py-1.5 text-xs uppercase tracking-wider hover:bg-muted"
            >
              <Minimize2 className="h-3 w-3" />
              Minimize
            </button>
          )}
          {phase === "terminal" && (
            <button
              onClick={() => closeIfSafe(false)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-xs font-semibold uppercase tracking-wider",
                terminalTone === "ok"
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : terminalTone === "unknown"
                    ? "bg-status-warn text-primary-foreground hover:bg-status-warn/90"
                    : "bg-status-crit text-primary-foreground hover:bg-status-crit/90",
              )}
            >
              Close
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LifecycleProgress({ status }: { status: RuntimeCommandStatus | null }) {
  const steps: Array<[RuntimeCommandStatus["state"], string]> = [
    ["SUBMITTING", "Submitted"],
    ["ACCEPTED", "Runtime accepted"],
    ["ACKNOWLEDGED", "Acknowledged"],
    ["IN_PROGRESS", "In progress"],
    ["COMPLETED", "Completed"],
  ];
  const order: RuntimeCommandStatus["state"][] = [
    "PREPARED",
    "SUBMITTING",
    "ACCEPTED",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
  ];
  const currentIdx = status ? order.indexOf(status.state) : 0;
  const failed =
    status?.state === "FAILED" ||
    status?.state === "TIMED_OUT" ||
    status?.state === "EXECUTION_UNKNOWN";

  return (
    <ul className="space-y-1">
      {steps.map(([key, label]) => {
        const idx = order.indexOf(key);
        const done = idx <= currentIdx && !failed;
        return (
          <li key={key} className="flex items-center gap-2">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                done ? "bg-status-ok" : "bg-muted-foreground/30",
              )}
            />
            <span className={done ? "text-foreground" : "text-muted-foreground"}>{label}</span>
          </li>
        );
      })}
      {failed && (
        <li className="mt-1 text-status-crit">
          {status?.state}: {status?.errorMessage ?? status?.message ?? "no details"}
        </li>
      )}
    </ul>
  );
}
