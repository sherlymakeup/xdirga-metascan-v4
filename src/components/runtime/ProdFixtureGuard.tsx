import { getRuntimeAdapter } from "@/lib/runtime";

/**
 * Loud, un-dismissable banner shown when a production build is running against
 * the DEVELOPMENT_FIXTURE data source. This is a shipping mistake — production
 * must be wired to a real local runtime. The banner does NOT block rendering
 * (the UI is a monitor, not a broker); it makes the misconfiguration truthful.
 */
export function ProdFixtureGuard() {
  if (!import.meta.env.PROD) return null;
  const adapter = getRuntimeAdapter();
  if (adapter.getDescriptor().dataSource !== "DEVELOPMENT_FIXTURE") return null;
  return (
    <div
      role="alert"
      className="border-b border-status-crit/60 bg-status-crit/15 px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-widest text-status-crit"
    >
      ⚠ Production build is using DEVELOPMENT_FIXTURE data · no local runtime connected · no broker
      linked · this deployment must be reconfigured
    </div>
  );
}
