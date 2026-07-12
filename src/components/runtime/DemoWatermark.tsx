import { getRuntimeAdapter } from "@/lib/runtime";
import { PRODUCT_BRAND } from "@/lib/constants/brand";

/**
 * Persistent watermark shown whenever the frontend is running against the
 * DEVELOPMENT_FIXTURE data source. Communicates truthfully that no local
 * runtime and no broker are connected.
 */
export function DemoWatermark() {
  const a = getRuntimeAdapter();
  if (a.adapterType !== "fixture") return null;
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed bottom-16 right-2 z-40 hidden select-none rounded-sm border border-status-warn/40 bg-status-warn/10 px-2 py-1 text-[9.5px] uppercase tracking-widest text-status-warn md:bottom-2 md:block"
    >
      <div className="font-semibold">{PRODUCT_BRAND.name} — DEVELOPMENT FIXTURE</div>
      <div className="text-status-warn/80">No local runtime · target broker: Exness TRIAL</div>
    </div>
  );
}
