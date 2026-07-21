// Builds a default RuntimeCapabilities set from the current snapshot.
// Backend authority is the eventual source of truth; the mock adapter uses this
// so UI buttons behave the way the real runtime will govern them.

import type { CockpitSnapshot } from "@/lib/types";
import type {
  CommandCapability,
  FrontendDataSource,
  RuntimeCapabilities,
  RuntimeCommandKind,
} from "./runtime-types";

type Cap = Omit<CommandCapability, "command">;

function cap(allowed: boolean, riskLevel: 1 | 2 | 3 | 4, opts: Partial<Cap> = {}): Cap {
  return {
    allowed,
    riskLevel,
    requiresReason: opts.requiresReason ?? riskLevel >= 3,
    requiresTypedConfirmation: opts.requiresTypedConfirmation ?? riskLevel >= 3,
    confirmationPhrase: opts.confirmationPhrase,
    reason: opts.reason,
  };
}

export function buildCapabilities(
  snap: CockpitSnapshot,
  source: FrontendDataSource = "DEVELOPMENT_FIXTURE",
): RuntimeCapabilities {
  const state = snap.runtime.state;
  const brokerUp = snap.broker.connection === "CONNECTED";
  const isRunning = state === "READY" || state === "DEGRADED";
  const isPaused = state === "PAUSED";
  const isStopped = state === "STOPPED" || state === "KILLED";
  const canOperate = isRunning && brokerUp;

  const blocked = (why: string): Partial<Cap> => ({ reason: why });

  const map: Partial<Record<RuntimeCommandKind, Cap>> = {
    "runtime.start": isStopped ? cap(true, 2) : cap(false, 2, blocked("Runtime already running")),
    "runtime.pause": isRunning ? cap(true, 2) : cap(false, 2, blocked("Runtime is not running")),
    "runtime.resume": isPaused ? cap(true, 2) : cap(false, 2, blocked("Runtime is not paused")),
    "runtime.stop": !isStopped ? cap(true, 3) : cap(false, 3, blocked("Runtime already stopped")),
    "runtime.restart": !isStopped ? cap(true, 3) : cap(false, 3, blocked("Runtime not running")),
    "runtime.reconnectBroker": !brokerUp
      ? cap(true, 2)
      : cap(true, 2, { requiresReason: false, requiresTypedConfirmation: false }),
    "runtime.reconcile": isRunning
      ? cap(true, 2)
      : cap(false, 2, blocked("Runtime must be running")),
    "runtime.disableEntries": snap.runtime.entriesEnabled
      ? cap(true, 2)
      : cap(false, 2, blocked("Entries already disabled")),
    "runtime.enableEntries": !snap.runtime.entriesEnabled
      ? cap(true, 2)
      : cap(false, 2, blocked("Entries already enabled")),
    "runtime.emergencyKill": !isStopped
      ? cap(true, 4, { confirmationPhrase: "KILL XDIRGA METASCAN" })
      : cap(false, 4, blocked("Runtime already stopped")),

    "strategy.pause": canOperate ? cap(true, 2) : cap(false, 2, blocked("Runtime not operational")),
    "strategy.resume": canOperate
      ? cap(true, 2)
      : cap(false, 2, blocked("Runtime not operational")),
    "strategy.disable": canOperate
      ? cap(true, 3)
      : cap(false, 3, blocked("Runtime not operational")),

    "order.cancel": canOperate ? cap(true, 2) : cap(false, 2, blocked("Broker offline")),
    "order.cancelAll": canOperate
      ? cap(true, 4, { confirmationPhrase: "CANCEL ALL ORDERS" })
      : cap(false, 4, blocked("Broker offline")),

    "position.close": canOperate ? cap(true, 3) : cap(false, 3, blocked("Broker offline")),
    "position.closePartial": canOperate ? cap(true, 3) : cap(false, 3, blocked("Broker offline")),
    "position.modifyProtection": canOperate
      ? cap(true, 3)
      : cap(false, 3, blocked("Broker offline")),
    "position.closeAll": canOperate
      ? cap(true, 4, { confirmationPhrase: "CLOSE ALL POSITIONS" })
      : cap(false, 4, blocked("Broker offline")),
    "position.management.pause": canOperate
      ? cap(true, 2, { requiresReason: false, requiresTypedConfirmation: false })
      : cap(false, 2, blocked("Broker offline")),
    "position.management.resume": canOperate
      ? cap(true, 2, { requiresReason: false, requiresTypedConfirmation: false })
      : cap(false, 2, blocked("Broker offline")),

    "breaker.reset": cap(true, 3),
    "alert.acknowledge": cap(true, 1, {
      requiresReason: false,
      requiresTypedConfirmation: false,
    }),
    "incident.acknowledge": cap(true, 1, {
      requiresReason: false,
      requiresTypedConfirmation: false,
    }),

    "config.validate": cap(true, 1, {
      requiresReason: false,
      requiresTypedConfirmation: false,
    }),
    "config.apply": cap(true, 3),
    "config.rollback": cap(true, 3),
  };

  const commands: RuntimeCapabilities["commands"] = {};
  for (const [k, v] of Object.entries(map)) {
    commands[k as RuntimeCommandKind] = { command: k as RuntimeCommandKind, ...v };
  }

  return {
    revision: 1,
    generatedAt: new Date().toISOString(),
    source,
    commands,
  };
}
