import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  title?: string;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  subtitle?: ReactNode;
  padded?: boolean;
  scroll?: boolean;
}

export function Panel({
  title,
  toolbar,
  children,
  className,
  bodyClassName,
  subtitle,
  padded = true,
  scroll = false,
}: Props) {
  const showHeader = Boolean(title || toolbar);
  return (
    <section className={cn("panel flex min-h-0 min-w-0 flex-col overflow-hidden", className)}>
      {showHeader && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-panel-border px-3 py-2">
          <div className="min-w-0 flex-1">
            {title && (
              <h2 className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</h2>
            )}
            {subtitle && <div className="mt-0.5 truncate text-xs text-muted-foreground">{subtitle}</div>}
          </div>
          {toolbar && <div className="flex shrink-0 items-center gap-1.5">{toolbar}</div>}
        </header>
      )}
      <div className={cn("min-h-0 flex-1", padded && "p-3", scroll && "overflow-auto", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}
