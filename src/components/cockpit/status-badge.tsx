import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusTone = "ok" | "info" | "warn" | "crit" | "neutral" | "strategy";

const toneClasses: Record<StatusTone, string> = {
  ok: "bg-status-ok/12 text-status-ok border-status-ok/30",
  info: "bg-status-info/12 text-status-info border-status-info/30",
  warn: "bg-status-warn/12 text-status-warn border-status-warn/40",
  crit: "bg-status-crit/15 text-status-crit border-status-crit/50",
  neutral: "bg-muted text-muted-foreground border-panel-border",
  strategy: "bg-status-strategy/12 text-status-strategy border-status-strategy/30",
};

const dotClasses: Record<StatusTone, string> = {
  ok: "bg-status-ok",
  info: "bg-status-info",
  warn: "bg-status-warn",
  crit: "bg-status-crit",
  neutral: "bg-status-neutral",
  strategy: "bg-status-strategy",
};

interface Props {
  tone: StatusTone;
  children: ReactNode;
  icon?: ReactNode;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
  size?: "sm" | "md";
  uppercase?: boolean;
}

export function StatusBadge({
  tone,
  children,
  icon,
  dot = true,
  pulse = false,
  className,
  size = "sm",
  uppercase = true,
}: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border font-medium tracking-wide",
        size === "sm" ? "px-1.5 py-0.5 text-[10.5px]" : "px-2 py-1 text-xs",
        uppercase && "uppercase",
        toneClasses[tone],
        className,
      )}
    >
      {dot && !icon && (
        <span className={cn("h-1.5 w-1.5 rounded-full", dotClasses[tone], pulse && "animate-pulse")} />
      )}
      {icon}
      <span className="whitespace-nowrap">{children}</span>
    </span>
  );
}
