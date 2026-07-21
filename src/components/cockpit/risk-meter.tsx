import { cn } from "@/lib/utils";

interface Props {
  value: number;
  warnAt: number;
  breachAt: number;
  label?: string;
  displayValue?: string;
  displayMax?: string;
  compact?: boolean;
  className?: string;
  /** When true, "lower is better" — inverts warn/breach direction (e.g. margin level). */
  inverted?: boolean;
}

export function RiskMeter({
  value,
  warnAt,
  breachAt,
  label,
  displayValue,
  displayMax,
  compact,
  className,
  inverted = false,
}: Props) {
  const max = Math.max(breachAt, value, warnAt) * 1.05;
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const warnPct = Math.min(100, (warnAt / max) * 100);
  const breachPct = Math.min(100, (breachAt / max) * 100);

  const breached = inverted ? value < breachAt : value >= breachAt;
  const warning = inverted ? value < warnAt : value >= warnAt;

  const fillColor = breached ? "bg-status-crit" : warning ? "bg-status-warn" : "bg-status-ok";

  return (
    <div className={cn("space-y-1", className)}>
      {label && (
        <div className="flex items-center justify-between text-[11px]">
          <span className="truncate text-muted-foreground">{label}</span>
          <span className="num text-foreground">
            {displayValue}
            {displayMax && <span className="text-muted-foreground"> / {displayMax}</span>}
          </span>
        </div>
      )}
      <div
        className={cn(
          "relative w-full overflow-hidden rounded-sm bg-muted",
          compact ? "h-1.5" : "h-2",
        )}
      >
        <div className={cn("h-full transition-all", fillColor)} style={{ width: `${pct}%` }} />
        <div
          className="absolute top-0 h-full w-px bg-status-warn/60"
          style={{ left: `${warnPct}%` }}
        />
        <div
          className="absolute top-0 h-full w-px bg-status-crit/70"
          style={{ left: `${breachPct}%` }}
        />
      </div>
    </div>
  );
}
