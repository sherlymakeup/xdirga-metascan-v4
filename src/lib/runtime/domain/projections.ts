// Domain event projections. Each projector consumes validated envelopes from
// the shared event history stream and maintains a small, focused in-memory
// store that pages can subscribe to via `useSyncExternalStore`.
//
// Projections are additive — they never mutate authoritative RuntimeAdapter
// snapshot state. They record the *last observed* per-entity view derived
// from the event stream so pages can surface live activity between snapshot
// refreshes without polling.

import { useSyncExternalStore } from "react";
import { eventHistoryStore } from "../events/event-store";
import { executionUnknownLocks } from "../state/execution-unknown-lock";
import type { RuntimeEventEnvelope } from "../runtime-types";
import type { PositionManagement } from "@/lib/types";

// -----------------------------------------------------------------------------
// Shared store primitive
// -----------------------------------------------------------------------------

type Listener = () => void;

class ProjectionStore<T> {
  private records = new Map<string, T>();
  private cachedList: T[] = [];
  private listeners = new Set<Listener>();

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  private emit() {
    this.cachedList = Array.from(this.records.values());
    for (const l of this.listeners) l();
  }

  upsert(id: string, patch: (prev: T | undefined) => T | undefined) {
    const prev = this.records.get(id);
    const next = patch(prev);
    if (!next) return;
    this.records.set(id, next);
    this.emit();
  }

  get = (id: string): T | undefined => this.records.get(id);
  list = (): T[] => this.cachedList;

  clear() {
    if (this.records.size === 0) return;
    this.records.clear();
    this.cachedList = [];
    this.emit();
  }
}

// -----------------------------------------------------------------------------
// Order projection
// -----------------------------------------------------------------------------

export interface OrderProjection {
  orderId: string;
  status?: string;
  symbol?: string;
  lastEventType: string;
  lastEventAt: string;
  correlationId?: string;
  commandId?: string;
  executionUnknown: boolean;
  source: RuntimeEventEnvelope["source"];
}

export const orderProjectionStore = new ProjectionStore<OrderProjection>();

// -----------------------------------------------------------------------------
// Position projection
// -----------------------------------------------------------------------------

export interface PositionProjection {
  positionId: string;
  symbol?: string;
  protection?: string;
  lastEventType: string;
  lastEventAt: string;
  correlationId?: string;
  commandId?: string;
  executionUnknown: boolean;
  source: RuntimeEventEnvelope["source"];
}

export const positionProjectionStore = new ProjectionStore<PositionProjection>();

// -----------------------------------------------------------------------------
// Incident projection
// -----------------------------------------------------------------------------

export interface IncidentProjection {
  incidentId: string;
  status: "OPEN" | "UPDATED" | "RESOLVED";
  severity: RuntimeEventEnvelope["severity"];
  lastEventType: string;
  lastEventAt: string;
  source: RuntimeEventEnvelope["source"];
}

export const incidentProjectionStore = new ProjectionStore<IncidentProjection>();

// -----------------------------------------------------------------------------
// Reconciliation run projection
// -----------------------------------------------------------------------------

export interface ReconciliationRunProjection {
  reconciliationRunId: string;
  status: "STARTED" | "ISSUE" | "RESOLVED" | "COMPLETED" | "FAILED";
  lastEventType: string;
  lastEventAt: string;
  source: RuntimeEventEnvelope["source"];
}

export const reconciliationRunProjectionStore =
  new ProjectionStore<ReconciliationRunProjection>();

// -----------------------------------------------------------------------------
// Position autopilot management projection
//
// Consumes the three `position.management.*` events and maintains the current
// `PositionManagement` view per positionId. Pages merge this with the
// authoritative snapshot value (projection wins whenever present).
// -----------------------------------------------------------------------------

export interface PositionManagementProjection extends PositionManagement {
  positionId: string;
  lastEventType: string;
  lastEventAt: string;
}

export const positionManagementProjectionStore =
  new ProjectionStore<PositionManagementProjection>();

/**
 * Pure reducer — exported for tests. Returns the next projection state given
 * the previous state (or undefined) and an envelope. Any envelope that is not
 * a `position.management.*` event returns `prev` unchanged.
 */
export function applyManagementEvent(
  prev: PositionManagementProjection | undefined,
  env: RuntimeEventEnvelope,
): PositionManagementProjection | undefined {
  if (!env.type.startsWith("position.management.")) return prev;
  const payload = (env.payload ?? {}) as Record<string, unknown>;
  const positionId =
    env.positionId ?? (payload.positionId as string | undefined);
  if (!positionId) return prev;
  const at = env.receivedAt ?? env.emittedAt;

  if (env.type === "position.management.plan_changed") {
    const plan = payload.plan as PositionManagement | undefined;
    if (!plan) return prev;
    return { ...plan, positionId, lastEventType: env.type, lastEventAt: at };
  }

  // action_executed / action_failed require an existing plan to mutate.
  if (!prev) return prev;

  if (env.type === "position.management.action_executed") {
    const action = payload.action as string | undefined;
    const detail = (payload.detail ?? {}) as Record<string, unknown>;
    if (action === "BREAK_EVEN") {
      return {
        ...prev,
        breakEven: {
          ...prev.breakEven,
          state: "APPLIED",
          appliedAt: (detail.appliedAt as string | undefined) ?? at,
        },
        lastError: null,
        lastEventType: env.type,
        lastEventAt: at,
      };
    }
    if (action === "TRAILING_MOVE") {
      const newStop = typeof detail.newStopPrice === "number"
        ? (detail.newStopPrice as number)
        : prev.trailing.currentStopPrice;
      return {
        ...prev,
        trailing: {
          ...prev.trailing,
          active: true,
          currentStopPrice: newStop,
          lastMovedAt: at,
          moveCount: prev.trailing.moveCount + 1,
        },
        lastError: null,
        lastEventType: env.type,
        lastEventAt: at,
      };
    }
    if (action === "PARTIAL_TP") {
      const levelId = detail.levelId as string | undefined;
      const executedPrice = detail.executedPrice as number | undefined;
      const closedVolume = detail.closedVolume as number | undefined;
      const levels = prev.partialTp.levels.map((l) =>
        l.levelId === levelId
          ? {
              ...l,
              state: "EXECUTED" as const,
              executedAt: at,
              executedPrice: executedPrice ?? l.executedPrice,
              closedVolume: closedVolume ?? l.closedVolume,
            }
          : l,
      );
      return {
        ...prev,
        partialTp: { levels },
        lastError: null,
        lastEventType: env.type,
        lastEventAt: at,
      };
    }
    if (action === "TIME_EXIT") {
      return {
        ...prev,
        timeExit: { ...prev.timeExit, state: "EXECUTED" },
        lastError: null,
        lastEventType: env.type,
        lastEventAt: at,
      };
    }
    return prev;
  }

  if (env.type === "position.management.action_failed") {
    const action = payload.action as string | undefined;
    const reason = (payload.reason as string | undefined) ?? "Unknown failure";
    const levelId = payload.levelId as string | undefined;
    let breakEven = prev.breakEven;
    let partialTp = prev.partialTp;
    if (action === "BREAK_EVEN") {
      breakEven = { ...prev.breakEven, state: "SKIPPED" };
    } else if (action === "PARTIAL_TP" && levelId) {
      partialTp = {
        levels: prev.partialTp.levels.map((l) =>
          l.levelId === levelId ? { ...l, state: "FAILED" as const } : l,
        ),
      };
    }
    return {
      ...prev,
      breakEven,
      partialTp,
      lastError: reason,
      lastEventType: env.type,
      lastEventAt: at,
    };
  }

  return prev;
}

// -----------------------------------------------------------------------------
// Envelope → projection routing
// -----------------------------------------------------------------------------

function project(env: RuntimeEventEnvelope) {
  const at = env.receivedAt ?? env.emittedAt;

  if (env.type.startsWith("position.management.")) {
    const positionId =
      env.positionId ??
      ((env.payload as { positionId?: string } | undefined)?.positionId);
    if (positionId) {
      positionManagementProjectionStore.upsert(positionId, (prev) =>
        applyManagementEvent(prev, env),
      );
    }
    // fall through so the position projection also records lastEventType.
  }


  if (env.orderId && env.type.startsWith("order.")) {
    orderProjectionStore.upsert(env.orderId, (prev) => ({
      orderId: env.orderId!,
      symbol:
        (env.payload as { symbol?: string } | undefined)?.symbol ?? prev?.symbol,
      status:
        (env.payload as { status?: string } | undefined)?.status ??
        env.type.split(".")[1] ??
        prev?.status,
      lastEventType: env.type,
      lastEventAt: at,
      correlationId: env.correlationId ?? prev?.correlationId,
      commandId: env.commandId ?? prev?.commandId,
      executionUnknown:
        env.type === "order.execution_unknown" ? true : prev?.executionUnknown ?? false,
      source: env.source,
    }));
  }

  if (env.positionId && env.type.startsWith("position.")) {
    positionProjectionStore.upsert(env.positionId, (prev) => ({
      positionId: env.positionId!,
      symbol:
        (env.payload as { symbol?: string } | undefined)?.symbol ?? prev?.symbol,
      protection:
        (env.payload as { protection?: string } | undefined)?.protection ??
        prev?.protection,
      lastEventType: env.type,
      lastEventAt: at,
      correlationId: env.correlationId ?? prev?.correlationId,
      commandId: env.commandId ?? prev?.commandId,
      executionUnknown:
        env.type === "position.execution_unknown"
          ? true
          : prev?.executionUnknown ?? false,
      source: env.source,
    }));
  }

  if (env.incidentId && env.type.startsWith("incident.")) {
    incidentProjectionStore.upsert(env.incidentId, (_prev) => {
      void _prev;
      const nextStatus: IncidentProjection["status"] =
        env.type === "incident.resolved"
          ? "RESOLVED"
          : env.type === "incident.updated"
            ? "UPDATED"
            : "OPEN";
      return {
        incidentId: env.incidentId!,
        status: nextStatus,
        severity: env.severity,
        lastEventType: env.type,
        lastEventAt: at,
        source: env.source,
      };
    });
  }

  if (env.reconciliationRunId && env.type.startsWith("reconciliation.")) {
    reconciliationRunProjectionStore.upsert(env.reconciliationRunId, (prev) => {
      let status: ReconciliationRunProjection["status"] = prev?.status ?? "STARTED";
      if (env.type === "reconciliation.started") status = "STARTED";
      else if (env.type === "reconciliation.issue.detected") status = "ISSUE";
      else if (env.type === "reconciliation.issue.resolved") status = "RESOLVED";
      else if (env.type === "reconciliation.completed") status = "COMPLETED";
      else if (env.type === "reconciliation.failed") status = "FAILED";
      return {
        reconciliationRunId: env.reconciliationRunId!,
        status,
        lastEventType: env.type,
        lastEventAt: at,
        source: env.source,
      };
    });

    // Release EXECUTION_UNKNOWN locks scoped to the reconciled entity, if any.
    if (
      env.type === "reconciliation.issue.resolved" ||
      env.type === "reconciliation.completed"
    ) {
      const payload = env.payload as
        | { entityId?: string; resolvedEntityIds?: string[] }
        | undefined;
      const ids: string[] = [];
      if (payload?.entityId) ids.push(payload.entityId);
      if (Array.isArray(payload?.resolvedEntityIds)) ids.push(...payload.resolvedEntityIds);
      if (env.orderId) ids.push(env.orderId);
      if (env.positionId) ids.push(env.positionId);
      for (const id of ids) executionUnknownLocks.releaseAllForTarget(id);
    }
  }
}

// -----------------------------------------------------------------------------
// Bootstrap — subscribe once to the event history store
// -----------------------------------------------------------------------------

let bootstrapped = false;
let lastProjectedId: string | null = null;
const projectedIds = new Set<string>();
const PROJECTED_ID_CAP = 4000;

export function bootstrapDomainProjections() {
  if (bootstrapped) return;
  bootstrapped = true;

  const drain = () => {
    const list = eventHistoryStore.list(); // newest first
    // Walk newest → oldest, collect until we hit an already-projected id.
    // If the last projected id has scrolled out of the bounded buffer, we
    // fall back to per-event dedup via `projectedIds` (guards against
    // duplicate projections after overflow).
    const fresh: RuntimeEventEnvelope[] = [];
    for (const env of list) {
      if (env.eventId === lastProjectedId) break;
      if (projectedIds.has(env.eventId)) continue;
      fresh.push(env);
    }
    // Apply oldest first for deterministic status transitions.
    for (let i = fresh.length - 1; i >= 0; i--) {
      const env = fresh[i];
      project(env);
      projectedIds.add(env.eventId);
    }
    if (list.length > 0) lastProjectedId = list[0].eventId;
    // Trim the dedup set to avoid unbounded growth.
    if (projectedIds.size > PROJECTED_ID_CAP) {
      const excess = projectedIds.size - Math.floor(PROJECTED_ID_CAP / 2);
      let dropped = 0;
      for (const id of projectedIds) {
        projectedIds.delete(id);
        if (++dropped >= excess) break;
      }
    }
  };

  eventHistoryStore.subscribe(drain);
  drain();
}

// -----------------------------------------------------------------------------
// Hooks
// -----------------------------------------------------------------------------

export function useOrderProjections(): OrderProjection[] {
  return useSyncExternalStore(
    orderProjectionStore.subscribe,
    () => orderProjectionStore.list(),
    () => orderProjectionStore.list(),
  );
}

export function usePositionProjections(): PositionProjection[] {
  return useSyncExternalStore(
    positionProjectionStore.subscribe,
    () => positionProjectionStore.list(),
    () => positionProjectionStore.list(),
  );
}

export function useIncidentProjections(): IncidentProjection[] {
  return useSyncExternalStore(
    incidentProjectionStore.subscribe,
    () => incidentProjectionStore.list(),
    () => incidentProjectionStore.list(),
  );
}

export function useReconciliationRunProjections(): ReconciliationRunProjection[] {
  return useSyncExternalStore(
    reconciliationRunProjectionStore.subscribe,
    () => reconciliationRunProjectionStore.list(),
    () => reconciliationRunProjectionStore.list(),
  );
}

export function usePositionManagementProjection(
  positionId: string | undefined,
): PositionManagementProjection | undefined {
  return useSyncExternalStore(
    positionManagementProjectionStore.subscribe,
    () => (positionId ? positionManagementProjectionStore.get(positionId) : undefined),
    () => (positionId ? positionManagementProjectionStore.get(positionId) : undefined),
  );
}

