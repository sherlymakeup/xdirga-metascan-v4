// Phase 5F.2 — Snapshot ↔ Event stream convergence tracker.
//
// The frontend receives two authoritative streams from the runtime:
//   1. Snapshot envelopes (authoritative state at a revision).
//   2. Event envelopes    (deltas + notifications tagged with revision).
//
// A healthy runtime keeps these converged: for a given bootId, the highest
// observed event revision should be within a small window of the last
// accepted snapshot revision. Drift means:
//   * event stream is ahead → a newer snapshot hasn't landed yet (transient).
//   * snapshot is ahead     → we missed events (gap / dropped subscription).
//
// This module maintains a live convergence view derived from both stores.
// It is read-only for the rest of the app.

import { useSyncExternalStore } from "react";
import { eventHistoryStore } from "../events/event-store";
import { snapshotHydrationStore } from "./snapshot-hydration";
import type { RuntimeEventEnvelope } from "../runtime-types";

export type ConvergenceStatus =
  | "UNKNOWN"
  | "CONVERGED"
  | "EVENTS_AHEAD"
  | "SNAPSHOT_AHEAD"
  | "BOOT_MISMATCH";

export interface ConvergenceState {
  status: ConvergenceStatus;
  snapshotBootId: string | null;
  snapshotRevision: number | null;
  snapshotSequence: number | null;
  latestEventBootId: string | null;
  latestEventRevision: number | null;
  latestEventSequence: number | null;
  revisionDrift: number | null; // events - snapshot (null if unknown)
  observedAt: string | null;
}

const CONVERGENCE_WINDOW = 5;
const INITIAL: ConvergenceState = {
  status: "UNKNOWN",
  snapshotBootId: null,
  snapshotRevision: null,
  snapshotSequence: null,
  latestEventBootId: null,
  latestEventRevision: null,
  latestEventSequence: null,
  revisionDrift: null,
  observedAt: null,
};

type Listener = () => void;

class ConvergenceStore {
  private state: ConvergenceState = INITIAL;
  private listeners = new Set<Listener>();
  private bootstrapped = false;

  subscribe = (l: Listener) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
  get = () => this.state;

  private emit() {
    for (const l of this.listeners) l();
  }

  bootstrap() {
    if (this.bootstrapped) return;
    this.bootstrapped = true;
    if (typeof window === "undefined") return;
    const recompute = () => this.recompute();
    eventHistoryStore.subscribe(recompute);
    snapshotHydrationStore.subscribe(recompute);
    recompute();
  }

  private recompute() {
    const hydration = snapshotHydrationStore.get();
    const events = eventHistoryStore.list();
    let latest: RuntimeEventEnvelope | null = null;
    for (const e of events) {
      // Ignore synthetic frontend-emitted system events (no real revision).
      if (e.runtimeId === "xdirga-runtime-frontend") continue;
      if (!latest) {
        latest = e;
        continue;
      }
      if (
        e.revision > latest.revision ||
        (e.revision === latest.revision && e.sequence > latest.sequence)
      ) {
        latest = e;
      }
    }

    const snapshotRevision = hydration.revision;
    const snapshotBootId = hydration.bootId;
    const latestEventRevision = latest?.revision ?? null;
    const latestEventBootId = latest?.bootId ?? null;

    let status: ConvergenceStatus = "UNKNOWN";
    let drift: number | null = null;

    if (snapshotRevision === null && latestEventRevision === null) {
      status = "UNKNOWN";
    } else if (
      snapshotBootId &&
      latestEventBootId &&
      snapshotBootId !== latestEventBootId
    ) {
      status = "BOOT_MISMATCH";
    } else if (snapshotRevision !== null && latestEventRevision !== null) {
      drift = latestEventRevision - snapshotRevision;
      if (Math.abs(drift) <= CONVERGENCE_WINDOW) status = "CONVERGED";
      else if (drift > 0) status = "EVENTS_AHEAD";
      else status = "SNAPSHOT_AHEAD";
    } else if (snapshotRevision !== null) {
      status = "SNAPSHOT_AHEAD";
    } else {
      status = "EVENTS_AHEAD";
    }

    const next: ConvergenceState = {
      status,
      snapshotBootId,
      snapshotRevision,
      snapshotSequence: hydration.sequence,
      latestEventBootId,
      latestEventRevision,
      latestEventSequence: latest?.sequence ?? null,
      revisionDrift: drift,
      observedAt: new Date().toISOString(),
    };

    const prev = this.state;
    if (
      prev.status === next.status &&
      prev.snapshotRevision === next.snapshotRevision &&
      prev.latestEventRevision === next.latestEventRevision &&
      prev.snapshotBootId === next.snapshotBootId &&
      prev.latestEventBootId === next.latestEventBootId &&
      prev.revisionDrift === next.revisionDrift
    ) {
      return;
    }
    this.state = next;
    this.emit();
  }
}

export const convergenceStore = new ConvergenceStore();

export function useConvergence(): ConvergenceState {
  return useSyncExternalStore(
    convergenceStore.subscribe,
    () => convergenceStore.get(),
    () => INITIAL,
  );
}
