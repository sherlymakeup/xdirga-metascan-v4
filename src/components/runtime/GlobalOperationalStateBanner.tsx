// Phase 5D — global operational-state banner + fixture diagnostics panel.
// Reads the centralized resolver — never invents its own rules.

import { AlertOctagon, ShieldAlert } from "lucide-react";
import { useGlobalOperationalState } from "@/lib/runtime/state/operational-state";
import { useExecutionUnknownLocks } from "@/lib/runtime/state/execution-unknown-lock";
import { useReconciliationRestriction } from "@/lib/runtime/state/reconciliation-restrictions";
import { useCommandCounts, useConnectionState, useHandshake } from "@/lib/runtime";
import { useApplicationHydration } from "@/lib/runtime/state/hydration";
import { scheduleFixtureManagementLifecycle } from "@/lib/runtime/events";

const TONE = {
  NORMAL: "hidden",
  DEGRADED: "border-status-warn/50 bg-status-warn/10 text-status-warn",
  RESTRICTED: "border-status-warn/60 bg-status-warn/15 text-status-warn",
  BLOCKED: "border-status-crit/50 bg-status-crit/10 text-status-crit",
  DISCONNECTED: "border-status-crit/50 bg-status-crit/10 text-status-crit",
  SAFE_MODE: "border-status-crit/60 bg-status-crit/15 text-status-crit",
} as const;

export function GlobalOperationalStateBanner() {
  const op = useGlobalOperationalState();
  if (op.state === "NORMAL") return null;
  return (
    <div className={`border-b px-3 py-2 text-[11.5px] md:px-4 ${TONE[op.state]}`}>
      <div className="mx-auto flex max-w-[1600px] items-start gap-2">
        {op.state === "SAFE_MODE" || op.state === "DISCONNECTED" ? (
          <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0" />
        ) : (
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
        )}
        <div className="min-w-0">
          <div className="font-semibold uppercase tracking-wider">
            Operational state: {op.state.replace("_", " ")}
          </div>
          {op.reasons.length > 0 && (
            <div className="mt-0.5 opacity-90">{op.reasons.join(" · ")}</div>
          )}
          {op.recommendedActions.length > 0 && (
            <div className="mt-0.5 opacity-80">
              Recommended: {op.recommendedActions.join(" · ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function FixtureDiagnosticsPanel() {
  if (import.meta.env.PROD) return null;
  const conn = useConnectionState();
  const handshake = useHandshake();
  const locks = useExecutionUnknownLocks();
  const reconciliation = useReconciliationRestriction();
  const counts = useCommandCounts();
  const hydration = useApplicationHydration();
  const op = useGlobalOperationalState();

  return (
    <div className="rounded-sm border border-panel-border bg-panel-elevated/60 p-3 text-[11px] text-muted-foreground">
      <div className="mb-2 font-semibold uppercase tracking-wider text-foreground">
        Development diagnostics
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-3">
        <Diag k="Source" v={conn.mode} />
        <Diag k="Connection" v={conn.state} />
        <Diag k="Hydration" v={hydration.state} />
        <Diag
          k="Handshake"
          v={handshake ? `${handshake.protocolId}@${handshake.protocolVersion}` : "—"}
        />
        <Diag k="Boot ID" v={handshake?.bootId ?? "—"} />
        <Diag k="Cap. revision" v={String(handshake?.capabilitiesRevision ?? "—")} />
        <Diag k="Cmd active" v={String(counts.active)} />
        <Diag k="Cmd failed" v={String(counts.failed)} />
        <Diag k="Cmd unknown" v={String(counts.unknown)} />
        <Diag k="Exec-unknown locks" v={String(locks.length)} />
        <Diag k="Reconciliation" v={reconciliation.blocked ? "BLOCKED" : "OK"} />
        <Diag k="Op state" v={op.state} />
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => scheduleFixtureManagementLifecycle()}
          className="rounded-sm border border-panel-border bg-panel px-2 py-1 text-[10.5px] font-medium uppercase tracking-wider hover:bg-muted"
        >
          Emit autopilot lifecycle (fx-pos-42)
        </button>
      </div>
    </div>
  );
}

function Diag({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2 truncate">
      <span className="uppercase tracking-wider text-[10px] text-muted-foreground/80">{k}</span>
      <span className="truncate font-mono text-foreground/90">{v}</span>
    </div>
  );
}
