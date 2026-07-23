import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@/lib/runtime/index", () => ({
  useSnapshot: () => ({ runtime: { state: "READY" }, broker: { connection: "DISCONNECTED" } }),
  useConnectionState: () => ({ state: "CONNECTED", dataAgeMs: 0 }),
  useHandshakeCompatibility: () => ({ safeMode: false }),
  useCapabilities: () => ({ commands: {} }),
  useCommandStore: () => [],
}));
vi.mock("@/lib/runtime/state/execution-unknown-lock", () => ({
  useExecutionUnknownLocks: () => [],
}));
vi.mock("@/lib/runtime/state/reconciliation-restrictions", () => ({
  useReconciliationRestriction: () => ({ blocked: false, affectedCommands: [] }),
}));

import { useGlobalOperationalState } from "@/lib/runtime/state/operational-state";

function Probe() {
  return <span>{useGlobalOperationalState().state}</span>;
}

it("marks broker snapshot disconnection as non-normal", () => {
  expect(renderToStaticMarkup(<Probe />)).not.toContain("NORMAL");
});
