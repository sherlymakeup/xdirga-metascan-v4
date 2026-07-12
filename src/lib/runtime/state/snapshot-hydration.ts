// Phase 5E.3 — Snapshot hydration + convergence store.
//
// Subscribes to the active adapter's snapshot stream and enforces monotonic
// acceptance: a snapshot is accepted only if it is from the same bootId with a
// strictly higher (revision, sequence), OR from a new bootId (which resets the
// window). Rejected envelopes are recorded with a reason so operators can see
// why a stale packet was ignored.

import { useSyncExternalStore } from "react";
import { getRuntimeAdapter } from "../index";
import type { RuntimeSnapshotEnvelope, SnapshotMetadata } from "../runtime-types";

export type SnapshotAcceptanceReason =
  | "ACCEPTED"
  | "ACCEPTED_NEW_BOOT"
  | "OLDER_REVISION"
  | "OLDER_SEQUENCE"
  | "OBSOLETE_BOOT"
  | "DUPLICATE";

export interface SnapshotHydrationState {
  hasSnapshot: boolean;
  runtimeId: string | null;
  bootId: string | null;
  revision: number | null;
  sequence: number | null;
  hydratedAt: string | null;
  lastReason: SnapshotAcceptanceReason | null;
  rejectedCount: number;
  acceptedCount: number;
}

type Listener = () => void;

const INITIAL: SnapshotHydrationState = {
  hasSnapshot: false,
  runtimeId: null,
  bootId: null,
  revision: null,
  sequence: null,
  hydratedAt: null,
  lastReason: null,
  rejectedCount: 0,
  acceptedCount: 0,
};

class SnapshotHydrationStore {
  private state: SnapshotHydrationState = INITIAL;
  private listeners = new Set<Listener>();
  private bootstrapped = false;

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
  get = (): SnapshotHydrationState => this.state;

  private emit() {
    for (const l of this.listeners) l();
  }

  ingest(env: RuntimeSnapshotEnvelope): SnapshotAcceptanceReason {
    const meta = env.metadata;
    const reason = this.evaluate(meta);
    if (reason === "ACCEPTED" || reason === "ACCEPTED_NEW_BOOT") {
      this.state = {
        hasSnapshot: true,
        runtimeId: meta.runtimeId,
        bootId: meta.bootId,
        revision: meta.revision,
        sequence: meta.sequence,
        hydratedAt: new Date().toISOString(),
        lastReason: reason,
        rejectedCount: this.state.rejectedCount,
        acceptedCount: this.state.acceptedCount + 1,
      };
    } else {
      this.state = {
        ...this.state,
        lastReason: reason,
        rejectedCount: this.state.rejectedCount + 1,
      };
    }
    this.emit();
    return reason;
  }

  private evaluate(meta: SnapshotMetadata): SnapshotAcceptanceReason {
    const s = this.state;
    if (!s.hasSnapshot) return "ACCEPTED";
    if (s.runtimeId && s.runtimeId !== meta.runtimeId) return "ACCEPTED_NEW_BOOT";
    if (s.bootId && s.bootId !== meta.bootId) return "ACCEPTED_NEW_BOOT";
    if (meta.revision < (s.revision ?? 0)) return "OLDER_REVISION";
    if (
      meta.revision === s.revision &&
      meta.sequence !== null &&
      meta.sequence < (s.sequence ?? 0)
    ) {
      return "OLDER_SEQUENCE";
    }
    if (meta.revision === s.revision && meta.sequence === s.sequence) return "DUPLICATE";
    return "ACCEPTED";
  }

  bootstrap() {
    if (this.bootstrapped) return;
    this.bootstrapped = true;
    if (typeof window === "undefined") return;
    const adapter = getRuntimeAdapter();
    // Seed with current snapshot envelope.
    try {
      this.ingest(adapter.getSnapshotEnvelope());
    } catch {
      /* ignore */
    }
    adapter.subscribeSnapshot((env) => this.ingest(env));
  }
}

export const snapshotHydrationStore = new SnapshotHydrationStore();

export function useSnapshotHydration(): SnapshotHydrationState {
  return useSyncExternalStore(
    snapshotHydrationStore.subscribe,
    () => snapshotHydrationStore.get(),
    () => INITIAL,
  );
}
