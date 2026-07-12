import { useState } from "react";
import { ShieldAlert, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { useHandshakeCompatibility } from "@/lib/runtime";
import { cn } from "@/lib/utils";

/**
 * Surface runtime protocol / schema drift as a prominent banner.
 * INCOMPATIBLE → red, safe mode active (all commands disabled by the capability layer).
 * WARN         → amber, informational; operator commands still allowed.
 * OK           → hidden.
 */
export function SchemaMismatchBanner() {
  const compat = useHandshakeCompatibility();
  const [expanded, setExpanded] = useState(false);

  if (!compat || compat.severity === "OK") return null;

  const isBlocking = compat.severity === "INCOMPATIBLE";
  const Icon = isBlocking ? ShieldAlert : AlertTriangle;

  const headline = isBlocking
    ? "Runtime incompatible — SAFE MODE engaged"
    : "Runtime protocol drift detected";

  const subline = isBlocking
    ? "Command execution is locked. Update the frontend or downgrade the runtime to a compatible build."
    : "The runtime reports a protocol or schema drift the frontend can tolerate. Review before issuing commands.";

  const actual = compat.actual;
  const expected = compat.expected;

  return (
    <div
      className={cn(
        "border-b px-3 py-2 text-[11.5px] md:px-4",
        isBlocking
          ? "border-status-crit/60 bg-status-crit/10 text-status-crit"
          : "border-status-warn/60 bg-status-warn/10 text-status-warn",
      )}
      role={isBlocking ? "alert" : "status"}
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold uppercase tracking-wider">{headline}</span>
            <span className="num text-[10px] uppercase tracking-wider opacity-80">
              {compat.reasons.length} {compat.reasons.length === 1 ? "issue" : "issues"}
            </span>
            {isBlocking && (
              <span className="rounded-sm bg-current/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                SAFE MODE
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] opacity-90">{subline}</p>

          {expanded && (
            <div className="mt-2 grid gap-3 text-[11px] md:grid-cols-2">
              <div className="rounded-sm border border-current/25 bg-current/[0.06] p-2">
                <div className="text-[10px] font-semibold uppercase tracking-widest opacity-80">
                  Frontend expects
                </div>
                <dl className="num mt-1 space-y-0.5">
                  <FieldRow label="Protocol" value={`${expected.protocolId} ${expected.protocolVersion}`} />
                  <FieldRow label="Schema" value={`${expected.schemaVersion}`} />
                  <FieldRow label="Min runtime" value={expected.minRuntimeVersion} />
                  <FieldRow label="Features" value={`${expected.requiredFeatures.length} required`} />
                  <FieldRow label="Commands" value={`${expected.requiredCommands.length} required`} />
                </dl>
              </div>
              <div className="rounded-sm border border-current/25 bg-current/[0.06] p-2">
                <div className="text-[10px] font-semibold uppercase tracking-widest opacity-80">
                  Runtime reports
                </div>
                {actual ? (
                  <dl className="num mt-1 space-y-0.5">
                    <FieldRow label="Runtime" value={`${actual.runtimeName} ${actual.runtimeVersion}`} />
                    <FieldRow label="Protocol" value={`${actual.protocolId} ${actual.protocolVersion}`} />
                    <FieldRow label="Schema" value={`${actual.schemaVersion}`} />
                    <FieldRow label="Schema hash" value={truncateHash(actual.schemaHash)} />
                    <FieldRow label="Broker env" value={actual.brokerEnvironment ?? "—"} />
                  </dl>
                ) : (
                  <p className="mt-1 opacity-80">No handshake received.</p>
                )}
              </div>
              <div className="md:col-span-2">
                <div className="text-[10px] font-semibold uppercase tracking-widest opacity-80">
                  Findings
                </div>
                <ul className="mt-1 space-y-1">
                  {compat.reasons.map((r: (typeof compat.reasons)[number], i: number) => (
                    <li
                      key={`${r.code}-${i}`}
                      className="flex items-start gap-2 rounded-sm border border-current/25 bg-current/[0.06] px-2 py-1"
                    >
                      <span
                        className={cn(
                          "num shrink-0 rounded-sm px-1 py-0.5 text-[9.5px] font-bold uppercase tracking-wider",
                          r.severity === "INCOMPATIBLE"
                            ? "bg-status-crit/25 text-status-crit"
                            : "bg-status-warn/25 text-status-warn",
                        )}
                      >
                        {r.severity}
                      </span>
                      <div className="min-w-0">
                        <div className="num text-[10.5px] font-semibold opacity-90">{r.code}</div>
                        <div className="text-[11px] opacity-90">{r.message}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto inline-flex items-center gap-1 rounded-sm border border-current/40 bg-transparent px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider hover:bg-current/10"
        >
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {expanded ? "Hide" : "Details"}
        </button>
      </div>
    </div>
  );
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-[10px] uppercase tracking-widest opacity-70">{label}</dt>
      <dd className="truncate text-[11px] font-semibold">{value}</dd>
    </div>
  );
}

function truncateHash(hash: string): string {
  if (hash.length <= 22) return hash;
  return `${hash.slice(0, 12)}…${hash.slice(-6)}`;
}
