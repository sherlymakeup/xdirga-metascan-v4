import type { RuntimeState } from "@/lib/types";
import { StatusBadge, type StatusTone } from "./status-badge";

const map: Record<RuntimeState, { tone: StatusTone; label: string; pulse?: boolean }> = {
  DISCONNECTED: { tone: "crit", label: "Disconnected" },
  INITIALIZING: { tone: "info", label: "Initializing", pulse: true },
  DEGRADED: { tone: "warn", label: "Degraded" },
  RECONNECTING: { tone: "warn", label: "Reconnecting", pulse: true },
  RECONCILING: { tone: "info", label: "Reconciling", pulse: true },
  READY: { tone: "ok", label: "Ready" },
  PAUSED: { tone: "neutral", label: "Paused" },
  STOPPING: { tone: "warn", label: "Stopping" },
  STOPPED: { tone: "neutral", label: "Stopped" },
  ERROR: { tone: "crit", label: "Error" },
  KILLED: { tone: "crit", label: "Killed" },
};

export function RuntimeStateBadge({ state, size }: { state: RuntimeState; size?: "sm" | "md" }) {
  const m = map[state];
  return (
    <StatusBadge tone={m.tone} pulse={m.pulse} size={size}>
      {m.label}
    </StatusBadge>
  );
}

// HMR warning only: tests share the component's canonical state-to-tone mapping.
// eslint-disable-next-line react-refresh/only-export-components
export function runtimeTone(state: RuntimeState): StatusTone {
  return map[state].tone;
}
