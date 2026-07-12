import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  AlertOctagon,
  BarChart3,
  Boxes,
  ClipboardList,
  Cog,
  Compass,
  FileClock,
  LineChart,
  ListChecks,
  Radar,
  Server,
  ShieldAlert,
  TerminalSquare,
  X,
} from "lucide-react";
import { useEffect } from "react";
import { useSnapshot } from "@/lib/adapters/runtime";
import { cn } from "@/lib/utils";
import { PRODUCT_BRAND } from "@/lib/constants/brand";
import { useBrokerEnvironment } from "@/lib/runtime/broker-environment";
import { RuntimeStateBadge } from "./runtime-state-badge";
import { StatusBadge } from "./status-badge";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Compass;
  badge?: (snap: ReturnType<typeof useSnapshot>) => { tone: "ok" | "info" | "warn" | "crit" | "neutral" | "strategy"; count: number } | null;
}

const items: NavItem[] = [
  { to: "/", label: "Cockpit", icon: Compass },
  { to: "/markets", label: "Markets", icon: Radar },
  { to: "/strategies", label: "Strategies", icon: LineChart },
  {
    to: "/orders",
    label: "Orders",
    icon: ClipboardList,
    badge: (s) => {
      const c = s.orders.filter((o) => o.status === "REJECTED" || o.status === "EXECUTION_UNKNOWN").length;
      return c > 0 ? { tone: "crit", count: c } : null;
    },
  },
  {
    to: "/positions",
    label: "Positions",
    icon: Boxes,
    badge: (s) => {
      const c = s.positions.filter((p) => p.protection !== "PROTECTED").length;
      return c > 0 ? { tone: "warn", count: c } : null;
    },
  },
  {
    to: "/risk",
    label: "Risk & Safety",
    icon: ShieldAlert,
    badge: (s) => {
      const c = s.breakers.filter((b) => b.state !== "CLOSED").length;
      return c > 0 ? { tone: "warn", count: c } : null;
    },
  },
  { to: "/runtime", label: "Runtime", icon: Server },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  {
    to: "/events",
    label: "Events & Logs",
    icon: FileClock,
    badge: (s) => {
      const c = s.alerts.filter((a) => !a.acknowledged && (a.severity === "CRITICAL" || a.severity === "HIGH")).length;
      return c > 0 ? { tone: "crit", count: c } : null;
    },
  },
  { to: "/configuration", label: "Configuration", icon: Cog },
  { to: "/system", label: "System", icon: TerminalSquare },
];

function SidebarNavList({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const snap = useSnapshot();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
        const badge = item.badge?.(snap) ?? null;
        const Icon = item.icon;
        return (
          <li key={item.to}>
            <Link
              to={item.to}
              onClick={onNavigate}
              className={cn(
                "group flex items-center gap-2.5 rounded-sm px-2 py-1.5 text-[13px] transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                collapsed && "justify-center px-0",
              )}
              title={collapsed ? item.label : undefined}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0",
                  active ? "text-primary" : "text-muted-foreground group-hover:text-foreground",
                )}
              />
              {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
              {!collapsed && badge && (
                <StatusBadge tone={badge.tone} size="sm" dot={false} uppercase={false}>
                  {badge.count}
                </StatusBadge>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function SidebarFooter({ collapsed }: { collapsed?: boolean }) {
  const snap = useSnapshot();
  const env = useBrokerEnvironment();
  return (
    <div className={cn("border-t border-panel-border px-3 py-2.5 text-[11px]", collapsed && "px-2")}>
      {!collapsed ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Runtime</span>
            <RuntimeStateBadge state={snap.runtime.state} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Data source</span>
            <StatusBadge tone={env.frontendDataSource === "LOCAL_RUNTIME" ? "ok" : "warn"} size="sm">
              {env.frontendDataSource === "LOCAL_RUNTIME" ? "LOCAL RUNTIME" : "FIXTURE"}
            </StatusBadge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Broker target</span>
            <span className="num text-foreground/90">{env.providerLabel}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Environment</span>
            <StatusBadge tone={env.target.environment === "LIVE" ? "crit" : "warn"} size="sm">
              {env.target.environment}
            </StatusBadge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Broker link</span>
            <StatusBadge
              tone={env.broker.state === "CONNECTED" ? "ok" : env.broker.state === "DEGRADED" ? "warn" : "crit"}
              size="sm"
            >
              {env.broker.state}
            </StatusBadge>
          </div>
          <div className="border-t border-panel-border/60 pt-1.5">
            <div className="text-[9.5px] uppercase tracking-wider text-muted-foreground">Local Runtime Engine</div>
            <div className="num text-[10.5px] text-foreground/80">{PRODUCT_BRAND.runtimeName}</div>
            <div className="num text-[10px] text-muted-foreground">v{snap.runtime.version} · {snap.runtime.buildHash}</div>
          </div>
        </div>
      ) : (
        <div className="flex justify-center">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              env.broker.state === "CONNECTED" ? "bg-status-ok" : "bg-status-warn",
            )}
          />
        </div>
      )}
    </div>
  );
}

export function AppSidebar({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <aside
      className={cn(
        "hidden md:flex sticky top-0 h-screen shrink-0 flex-col border-r border-panel-border bg-sidebar",
        collapsed ? "w-14" : "w-56",
      )}
    >
      <div className={cn("flex items-center gap-2 border-b border-panel-border px-3 py-3", collapsed && "justify-center px-2")}>
        <div className="grid h-7 w-7 place-items-center rounded-sm bg-primary/15 text-primary">
          <Activity className="h-4 w-4" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold tracking-tight">{PRODUCT_BRAND.name}</div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {PRODUCT_BRAND.category}
            </div>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-1.5 py-2">
        <SidebarNavList collapsed={collapsed} />
      </nav>

      <SidebarFooter collapsed={collapsed} />
    </aside>
  );
}

export function MobileSidebarDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Lock body scroll while open + close on Escape
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

  return (
    <div
      className={cn(
        "md:hidden fixed inset-0 z-50 transition-opacity",
        open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
      aria-hidden={!open}
    >
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="absolute inset-0 bg-background/70 backdrop-blur-sm"
      />
      {/* Panel */}
      <aside
        role="dialog"
        aria-label="Navigation"
        className={cn(
          "absolute inset-y-0 left-0 flex w-[78%] max-w-[300px] flex-col border-r border-panel-border bg-sidebar shadow-2xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center gap-2 border-b border-panel-border px-3 py-3">
          <div className="grid h-7 w-7 place-items-center rounded-sm bg-primary/15 text-primary">
            <Activity className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold tracking-tight">{PRODUCT_BRAND.name}</div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{PRODUCT_BRAND.category}</div>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-md border border-panel-border bg-panel-elevated text-muted-foreground active:bg-muted"
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-1.5 py-2">
          <SidebarNavList onNavigate={onClose} />
        </nav>

        <SidebarFooter />
      </aside>
    </div>
  );
}

export function MobileBottomNav() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const snap = useSnapshot();
  const unresolved = snap.alerts.filter((a) => !a.acknowledged).length;
  const mobileItems = [
    { to: "/", label: "Cockpit", icon: Compass },
    { to: "/positions", label: "Positions", icon: Boxes },
    { to: "/orders", label: "Orders", icon: ClipboardList },
    { to: "/events", label: "Alerts", icon: AlertOctagon, badge: unresolved },
    { to: "/runtime", label: "More", icon: ListChecks },
  ];
  return (
    <nav className="md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-panel-border bg-sidebar/95 backdrop-blur">
      <ul className="grid grid-cols-5">
        {mobileItems.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          const Icon = item.icon;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                className={cn(
                  "relative flex flex-col items-center gap-0.5 px-2 py-2 text-[10px]",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
                {item.badge ? (
                  <span className="absolute right-3 top-1 min-w-[16px] rounded-full bg-status-crit px-1 text-[9px] font-semibold text-primary-foreground">
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="h-[env(safe-area-inset-bottom)]" />
    </nav>
  );
}
