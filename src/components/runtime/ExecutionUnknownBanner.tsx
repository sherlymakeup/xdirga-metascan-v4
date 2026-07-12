import { AlertOctagon } from "lucide-react";
import { useCommandStore } from "@/lib/runtime";

/**
 * Global banner shown whenever any command is in EXECUTION_UNKNOWN state.
 * Instructs the operator not to retry until reconciliation resolves broker state.
 */
export function ExecutionUnknownBanner() {
  const commands = useCommandStore();
  const unknown = commands.filter((c) => c.state === "EXECUTION_UNKNOWN");
  if (unknown.length === 0) return null;

  return (
    <div className="border-b border-status-crit/50 bg-status-crit/10 px-3 py-2 text-[11.5px] text-status-crit md:px-4">
      <div className="mx-auto flex max-w-[1600px] items-start gap-2">
        <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          <div className="font-semibold uppercase tracking-wider">
            Execution result is unknown ({unknown.length})
          </div>
          <p className="mt-0.5 text-status-crit/90">
            One or more trading commands did not return a confirmed broker outcome. Do not retry —
            open the command center and run reconciliation to determine actual broker state.
          </p>
        </div>
      </div>
    </div>
  );
}
