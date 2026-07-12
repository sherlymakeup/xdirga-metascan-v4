import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 py-8 text-center", className)}>
      <div className="grid h-9 w-9 place-items-center rounded-full bg-muted text-muted-foreground">
        {icon ?? <Info className="h-4 w-4" />}
      </div>
      <div className="text-sm font-medium">{title}</div>
      {description && <p className="max-w-sm text-xs text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({
  title,
  message,
  onRetry,
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-sm border border-status-crit/30 bg-status-crit/5 py-6 text-center",
        className,
      )}
    >
      <div className="text-sm font-semibold text-status-crit">{title ?? "Something failed"}</div>
      <p className="max-w-sm text-xs text-muted-foreground">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-1 rounded-sm border border-panel-border bg-panel-elevated px-2 py-1 text-xs hover:bg-muted"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function StaleDataOverlay({
  ageSec,
  onRefresh,
}: {
  ageSec: number;
  onRefresh?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-sm border border-status-warn/30 bg-status-warn/5 px-2 py-1 text-[11px] text-status-warn">
      <span>
        Data stale — last update {ageSec}s ago. Trading decisions may be based on outdated values.
      </span>
      {onRefresh && (
        <button onClick={onRefresh} className="rounded-sm border border-status-warn/40 px-1.5 py-0.5">
          Refresh
        </button>
      )}
    </div>
  );
}
