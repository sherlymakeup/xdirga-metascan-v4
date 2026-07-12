// Phase 5D — Execution-Unknown lock registry.
// When any command lands in EXECUTION_UNKNOWN we lock the affected entities so
// operators cannot spam duplicate cancels/closes/orders while broker truth is
// undetermined. Locks are released ONLY by reconciliation (or a fixture
// scenario that simulates reconciliation), never by local dismissal.

import { useSyncExternalStore } from "react";
import type { RuntimeCommandKind } from "../runtime-types";

export interface ExecutionUnknownLock {
  key: string;
  commandId: string;
  kind: RuntimeCommandKind;
  targetId?: string;
  symbol?: string;
  strategy?: string;
  correlationId?: string;
  operation: "CLOSE" | "CANCEL" | "SUBMIT" | "PROTECTION" | "KILL_STEP" | "MANAGEMENT" | "OTHER";
  createdAt: string;
}

type Listener = () => void;

function operationFor(kind: RuntimeCommandKind): ExecutionUnknownLock["operation"] {
  if (kind.startsWith("position.management.")) return "MANAGEMENT";
  if (kind.startsWith("position.close")) return "CLOSE";
  if (kind === "position.modifyProtection") return "PROTECTION";
  if (kind === "order.cancel" || kind === "order.cancelAll") return "CANCEL";
  if (kind === "runtime.emergencyKill") return "KILL_STEP";
  if (kind.startsWith("order.")) return "SUBMIT";
  return "OTHER";
}

function keyFor(kind: RuntimeCommandKind, targetId?: string): string {
  return `${operationFor(kind)}:${targetId ?? "-"}`;
}

class ExecutionUnknownLockRegistry {
  private locks = new Map<string, ExecutionUnknownLock>();
  private listeners = new Set<Listener>();
  private listCache: ExecutionUnknownLock[] = [];

  subscribe(l: Listener) {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  }

  private emit() {
    this.listCache = Array.from(this.locks.values());
    for (const l of this.listeners) l();
  }

  acquire(input: Omit<ExecutionUnknownLock, "key" | "createdAt">): ExecutionUnknownLock {
    const key = keyFor(input.kind, input.targetId);
    const lock: ExecutionUnknownLock = {
      ...input,
      key,
      createdAt: new Date().toISOString(),
    };
    this.locks.set(key, lock);
    this.emit();
    return lock;
  }

  /** Reconciliation-only. Do NOT expose to UI dismiss buttons. */
  releaseByReconciliation(key: string): boolean {
    const removed = this.locks.delete(key);
    if (removed) this.emit();
    return removed;
  }

  releaseAllForTarget(targetId: string): number {
    let n = 0;
    for (const [k, lock] of this.locks) {
      if (lock.targetId === targetId) {
        this.locks.delete(k);
        n++;
      }
    }
    if (n) this.emit();
    return n;
  }

  isBlocked(kind: RuntimeCommandKind, targetId?: string): ExecutionUnknownLock | undefined {
    return this.locks.get(keyFor(kind, targetId));
  }

  list(): ExecutionUnknownLock[] {
    return this.listCache;
  }

  clear() {
    if (this.locks.size === 0) return;
    this.locks.clear();
    this.emit();
  }
}

export const executionUnknownLocks = new ExecutionUnknownLockRegistry();

export function useExecutionUnknownLocks(): ExecutionUnknownLock[] {
  return useSyncExternalStore(
    (l) => executionUnknownLocks.subscribe(l),
    () => executionUnknownLocks.list(),
    () => executionUnknownLocks.list(),
  );
}
