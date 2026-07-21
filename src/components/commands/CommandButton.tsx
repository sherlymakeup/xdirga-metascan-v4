// CommandButton — capability-gated trigger for runtime commands.
// Phase 5E: every submission goes through the central command orchestrator.
// Confirmation dialog stays open through the full lifecycle (via live status)
// until a terminal state, and blocked results are surfaced in-dialog rather
// than as thrown errors.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertOctagon, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ConfirmationDialog, type ConfirmationSubmitResult } from "@/components/cockpit/confirmation-dialog";
import { EnvironmentImpactPanel } from "@/components/runtime/environment-badges";
import {
  submitCommand,
  useCapability,
  getRuntimeMode,
  useCommand,
} from "@/lib/runtime";
import type { RuntimeCommandKind } from "@/lib/runtime";

export type CommandButtonVariant = "default" | "outline" | "ghost" | "danger" | "primary";

interface CommandButtonProps {
  kind: RuntimeCommandKind;
  label: ReactNode;
  icon?: ReactNode;
  /** Optional target resource id (positionId, orderId, breaker key, etc.) */
  targetId?: string;
  parameters?: Record<string, unknown>;
  /** Idempotency key; defaults to `${kind}:${targetId ?? "global"}`. */
  idempotencyKey?: string;
  /** Optional dialog copy overrides. */
  title?: string;
  description?: ReactNode;
  impactSummary?: ReactNode;
  confirmLabel?: string;
  /** Force override capability confirmation phrase (rare). */
  confirmPhrase?: string;
  /** Skip confirmation entirely (only allowed for riskLevel === 1). */
  skipConfirmation?: boolean;
  variant?: CommandButtonVariant;
  size?: "sm" | "md";
  className?: string;
  fullWidth?: boolean;
  /** Called with the final command status when it reaches a terminal state. */
  onSettled?: (status: ReturnType<typeof useCommand>) => void;
}

const variantClasses: Record<CommandButtonVariant, string> = {
  default:
    "border border-panel-border bg-panel-elevated text-foreground hover:bg-muted",
  outline:
    "border border-panel-border bg-transparent text-foreground hover:bg-panel-elevated",
  ghost: "bg-transparent text-foreground hover:bg-panel-elevated",
  primary:
    "bg-primary text-primary-foreground hover:bg-primary/90 border border-transparent",
  danger:
    "bg-status-crit text-primary-foreground hover:bg-status-crit/90 border border-transparent",
};

export function CommandButton(props: CommandButtonProps) {
  if (getRuntimeMode() !== "fixture") return null;
  return <DemoCommandButton {...props} />;
}

function DemoCommandButton({
  kind,
  label,
  icon,
  targetId,
  parameters,
  idempotencyKey,
  title,
  description,
  impactSummary,
  confirmLabel,
  confirmPhrase,
  skipConfirmation,
  variant = "default",
  size = "sm",
  className,
  fullWidth,
  onSettled,
}: CommandButtonProps) {
  const capability = useCapability(kind);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [commandId, setCommandId] = useState<string | null>(null);
  const activeStatus = useCommand(commandId);

  const allowed = capability?.allowed ?? false;
  const riskLevel = capability?.riskLevel ?? 2;
  const busy = activeStatus
    ? !["COMPLETED", "FAILED", "TIMED_OUT", "EXECUTION_UNKNOWN", "CANCELLED"].includes(
        activeStatus.state,
      )
    : false;

  useEffect(() => {
    if (!activeStatus || !onSettled) return;
    if (
      ["COMPLETED", "FAILED", "TIMED_OUT", "EXECUTION_UNKNOWN", "CANCELLED"].includes(
        activeStatus.state,
      )
    ) {
      onSettled(activeStatus);
    }
  }, [activeStatus, onSettled]);

  const effectivePhrase = confirmPhrase ?? capability?.confirmationPhrase;
  const canSkip = skipConfirmation && riskLevel === 1;

  const submit = async (reason: string): Promise<ConfirmationSubmitResult> => {
    const result = await submitCommand({
      kind,
      targetId,
      reason: reason || undefined,
      parameters,
      idempotencyKey,
    });
    if (result.accepted && result.commandId) {
      setCommandId(result.commandId);
      return { accepted: true, commandId: result.commandId };
    }
    return {
      accepted: false,
      blockedReason: result.blockedReason ?? "Command was blocked by preflight checks.",
    };
  };

  const openOrSubmit = async () => {
    if (canSkip) {
      await submit("");
      return;
    }
    setDialogOpen(true);
  };

  const disabled = !allowed || busy;
  const disabledReason = !allowed
    ? capability?.reason ?? "Command not available in the current runtime state."
    : busy
      ? "Command in progress"
      : undefined;

  const dialogTitle = useMemo(() => title ?? defaultTitle(kind), [title, kind]);
  const dialogDescription = description ?? defaultDescription(kind);
  const cta = confirmLabel ?? defaultCta(kind);

  return (
    <>
      <button
        type="button"
        onClick={openOrSubmit}
        disabled={disabled}
        title={disabledReason}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 rounded-sm font-medium uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-40",
          size === "sm" ? "px-2.5 py-1.5 text-[11px]" : "px-3 py-2 text-xs",
          fullWidth && "w-full",
          variantClasses[variant],
          className,
        )}
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
        <span className="truncate">{label}</span>
        {activeStatus?.state === "EXECUTION_UNKNOWN" && (
          <AlertOctagon className="h-3 w-3 text-status-crit" />
        )}
      </button>

      {dialogOpen && (
        <ConfirmationDialog
          open
          onOpenChange={(v) => !v && setDialogOpen(false)}
          level={riskLevel}
          title={dialogTitle}
          description={dialogDescription}
          impactSummary={
            <div className="space-y-3">
              {impactSummary && <div>{impactSummary}</div>}
              <EnvironmentImpactPanel />
            </div>
          }
          confirmPhrase={effectivePhrase}
          confirmLabel={cta}
          requireReason={capability?.requiresReason}
          destructive={riskLevel >= 3 || variant === "danger"}
          onConfirm={submit}
          commandStatus={activeStatus ?? null}
        />
      )}
    </>
  );
}


function defaultTitle(kind: RuntimeCommandKind): string {
  const map: Partial<Record<RuntimeCommandKind, string>> = {
    "runtime.start": "Start runtime",
    "runtime.pause": "Pause runtime",
    "runtime.resume": "Resume runtime",
    "runtime.stop": "Stop runtime",
    "runtime.restart": "Restart runtime",
    "runtime.reconnectBroker": "Reconnect broker",
    "runtime.reconcile": "Run reconciliation",
    "runtime.disableEntries": "Disable new entries",
    "runtime.enableEntries": "Enable new entries",
    "runtime.emergencyKill": "EMERGENCY KILL",
    "order.cancel": "Cancel order",
    "order.cancelAll": "Cancel ALL orders",
    "position.close": "Close position",
    "position.closeAll": "Close ALL positions",
    "position.closePartial": "Close position (partial)",
    "position.modifyProtection": "Modify protection",
    "breaker.reset": "Reset circuit breaker",
    "strategy.pause": "Pause strategy",
    "strategy.resume": "Resume strategy",
    "strategy.disable": "Disable strategy",
    "alert.acknowledge": "Acknowledge alert",
    "incident.acknowledge": "Acknowledge incident",
    "config.validate": "Validate configuration",
    "config.apply": "Apply configuration",
    "config.rollback": "Rollback configuration",
  };
  return map[kind] ?? kind;
}

function defaultDescription(kind: RuntimeCommandKind): string {
  return `Submit ${kind} to the local runtime. The command lifecycle will be tracked in the Command Center.`;
}

function defaultCta(kind: RuntimeCommandKind): string {
  if (kind === "runtime.emergencyKill") return "KILL NOW";
  if (kind.startsWith("runtime.")) return kind.split(".")[1];
  if (kind === "order.cancelAll") return "Cancel all";
  if (kind === "position.closeAll") return "Close all";
  return "Confirm";
}
