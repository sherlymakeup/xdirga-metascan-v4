import { useState } from "react";
import { Wifi, WifiOff, Loader2, RefreshCw } from "lucide-react";
import { getRuntimeAdapter, useConnectionState } from "@/lib/runtime";
import { cn } from "@/lib/utils";

/**
 * Runtime connection banner. Hidden when CONNECTED. Otherwise shows the connection
 * state so operators are never left believing they are viewing live data.
 */
export function ConnectionBanner() {
  const conn = useConnectionState();
  const [busy, setBusy] = useState(false);

  if (conn.state === "CONNECTED") return null;

  const tone =
    conn.state === "ERROR" || conn.state === "DISCONNECTED"
      ? "crit"
      : conn.state === "STALE"
        ? "warn"
        : "info";

  const label: Record<Exclude<typeof conn.state, "CONNECTED">, string> = {
    DISCONNECTED: "Runtime disconnected",
    CONNECTING: "Connecting to runtime",
    RECONNECTING: "Reconnecting to runtime",
    STALE: "Runtime data is stale",
    ERROR: "Runtime connection error",
  };

  const canReconnect = conn.state === "DISCONNECTED" || conn.state === "ERROR" || conn.state === "STALE";
  const reconnect = async () => {
    setBusy(true);
    try {
      await getRuntimeAdapter().connect();
    } catch {
      /* surfaced via connection state */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={cn(
        "border-b px-3 py-1.5 text-[11.5px] md:px-4",
        tone === "crit" && "border-status-crit/50 bg-status-crit/10 text-status-crit",
        tone === "warn" && "border-status-warn/50 bg-status-warn/10 text-status-warn",
        tone === "info" && "border-status-info/50 bg-status-info/10 text-status-info",
      )}
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2">
        {conn.state === "RECONNECTING" || conn.state === "CONNECTING" ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
        ) : conn.state === "STALE" ? (
          <Wifi className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <WifiOff className="h-3.5 w-3.5 shrink-0" />
        )}
        <span className="font-semibold uppercase tracking-wider">{label[conn.state]}</span>
        <span className="num text-[10px] uppercase tracking-wider opacity-70">
          {conn.adapterType} · {conn.mode}
        </span>
        {conn.errorMessage && <span className="min-w-0 truncate">— {conn.errorMessage}</span>}
        {typeof conn.dataAgeMs === "number" && conn.dataAgeMs > 0 && (
          <span className="num text-[10.5px] opacity-80">data {Math.round(conn.dataAgeMs / 1000)}s old</span>
        )}
        {canReconnect && (
          <button
            type="button"
            onClick={reconnect}
            disabled={busy}
            className="ml-auto inline-flex items-center gap-1 rounded-sm border border-current/40 bg-transparent px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider hover:bg-current/10 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            Reconnect
          </button>
        )}
      </div>
    </div>
  );
}
