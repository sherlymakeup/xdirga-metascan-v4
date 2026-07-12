// Phase 5D — application hydration lifecycle. Truthful startup states so the
// UI never flashes false zero balances or "connected" chips before hydration.

import { useMemo } from "react";
import { useConnectionState, useHandshake, useSnapshot } from "../index";
import { useSnapshotHydration } from "./snapshot-hydration";
import type { FrontendDataSource } from "../runtime-types";

export type ApplicationHydrationState =
  | "BOOTSTRAPPING"
  | "LOADING_FIXTURE"
  | "CONNECTING_RUNTIME"
  | "HYDRATING_SNAPSHOT"
  | "READY"
  | "DEGRADED"
  | "FAILED";

export interface HydrationSummary {
  state: ApplicationHydrationState;
  source: FrontendDataSource;
  handshakeKnown: boolean;
  snapshotRevision: number | null;
  snapshotSequence: number | null;
  bootId: string | null;
  hydratedAt: string | null;
  hasSnapshot: boolean;
}

export interface SnapshotHydrationResult {
  accepted: boolean;
  reason?:
    | "OLDER_REVISION"
    | "OLDER_SEQUENCE"
    | "OBSOLETE_BOOT"
    | "INVALID_SCHEMA"
    | "DUPLICATE"
    | "ACCEPTED";
  previousRevision?: number;
  nextRevision?: number;
  hydratedAt: string;
}

export function useApplicationHydration(): HydrationSummary {
  const conn = useConnectionState();
  const handshake = useHandshake();
  const snapshot = useSnapshot();
  const hydration = useSnapshotHydration();

  return useMemo<HydrationSummary>(() => {
    const source = conn.mode;
    const hasSnapshot = hydration.hasSnapshot || Boolean(snapshot?.runtime?.id);
    const handshakeKnown = handshake !== null;

    let state: ApplicationHydrationState;
    if (conn.state === "ERROR") state = "FAILED";
    else if (!hasSnapshot && source === "DEVELOPMENT_FIXTURE") state = "LOADING_FIXTURE";
    else if (!handshakeKnown && conn.state === "CONNECTING") state = "CONNECTING_RUNTIME";
    else if (!hasSnapshot) state = "HYDRATING_SNAPSHOT";
    else if (conn.state === "STALE" || conn.state === "RECONNECTING") state = "DEGRADED";
    else if (conn.state === "DISCONNECTED") state = "DEGRADED";
    else state = "READY";

    return {
      state,
      source,
      handshakeKnown,
      snapshotRevision: hydration.revision,
      snapshotSequence: hydration.sequence,
      bootId: hydration.bootId,
      hydratedAt: hydration.hydratedAt,
      hasSnapshot,
    };
  }, [conn, handshake, snapshot, hydration]);
}
