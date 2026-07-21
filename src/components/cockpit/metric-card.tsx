import type { ReactNode } from "react";
import type { DataFreshness } from "@/lib/types";
import { cn } from "@/lib/utils";
import { StatusBadge, type StatusTone } from "./status-badge";

interface MetricProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: StatusTone;
  delta?: number;
  deltaLabel?: string;
  freshness?: DataFreshness;
  loading?: boolean;
  unavailable?: boolean;
  compact?: boolean;
  className?: string;
}

const freshnessMap: Record<DataFreshness, { tone: StatusTone; label: string }> = {
  FRESH: { tone: "ok", label: "Fresh" },
  DELAYED: { tone: "warn", label: "Delayed" },
  STALE: { tone: "crit", label: "Stale" },
  UNAVAILABLE: { tone: "neutral", label: "Unavailable" },
};

export function MetricCard({
  label,
  value,
  hint,
  tone,
  delta,
  deltaLabel,
  freshness,
  loading,
  unavailable,
  compact,
  className,
}: MetricProps) {
  const showValue = !loading && !unavailable;
  const deltaTone =
    delta == null
      ? undefined
      : delta > 0
        ? "text-profit"
        : delta < 0
          ? "text-loss"
          : "text-muted-foreground";
  const valueColor =
    tone === "ok"
      ? "text-status-ok"
      : tone === "warn"
        ? "text-status-warn"
        : tone === "crit"
          ? "text-status-crit"
          : tone === "info"
            ? "text-status-info"
            : "text-foreground";

  return (
    <div
      className={cn(
        "panel flex flex-col justify-between gap-1.5",
        compact ? "p-2.5" : "p-3",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="truncate text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </div>
        {freshness && freshness !== "FRESH" && (
          <StatusBadge tone={freshnessMap[freshness].tone} size="sm">
            {freshnessMap[freshness].label}
          </StatusBadge>
        )}
      </div>

      {loading && <div className="h-6 w-24 animate-pulse rounded bg-muted" />}
      {unavailable && <div className="text-sm text-muted-foreground italic">Unavailable</div>}
      {showValue && (
        <div
          className={cn(
            "num text-xl leading-tight font-semibold",
            compact && "text-lg",
            valueColor,
          )}
        >
          {value}
        </div>
      )}
      {!loading && (
        <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span className="truncate">{hint}</span>
          {delta != null && (
            <span className={cn("num tabular", deltaTone)}>
              {delta > 0 ? "▲" : delta < 0 ? "▼" : "▪"} {Math.abs(delta).toFixed(2)}
              {deltaLabel && <span className="ml-1 text-muted-foreground">{deltaLabel}</span>}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
