// Runtime command store — global, survives route changes.
// Records the full lifecycle of every command submitted through the adapter.
//
// Phase 5E: every state mutation is funneled through `validateTransition`.
// Invalid transitions are rejected, do NOT mutate state, and emit a
// `system.validation.failed` envelope through the event history store.
// Entering `EXECUTION_UNKNOWN` auto-acquires an execution-unknown lock so
// operators cannot spam duplicate destructive commands while broker truth
// is undetermined.

import type {
  RuntimeCommandKind,
  RuntimeCommandRequest,
  RuntimeCommandStatus,
} from "./runtime-types";
import { validateTransition } from "./commands/command-transitions";
import { executionUnknownLocks } from "./state/execution-unknown-lock";

const MAX_HISTORY = 200;

type Listener = () => void;

class CommandStore {
  private commands = new Map<string, RuntimeCommandStatus>();
  private byIdempotency = new Map<string, string>(); // idempotencyKey -> commandId
  private listeners = new Set<Listener>();
  private listCache: RuntimeCommandStatus[] = [];
  private countsCache = { active: 0, failed: 0, unknown: 0, completed: 0 };

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private recomputeCaches() {
    this.listCache = Array.from(this.commands.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
    let active = 0;
    let failed = 0;
    let unknown = 0;
    let completed = 0;
    for (const c of this.commands.values()) {
      if (c.state === "COMPLETED") completed++;
      else if (c.state === "FAILED" || c.state === "TIMED_OUT") failed++;
      else if (c.state === "EXECUTION_UNKNOWN") unknown++;
      else if (!isTerminal(c.state)) active++;
    }
    this.countsCache = { active, failed, unknown, completed };
  }

  private emit() {
    this.recomputeCaches();
    for (const l of this.listeners) l();
  }

  /** Look up an active (non-terminal) command by idempotency key. */
  findActiveByIdempotency(key: string): RuntimeCommandStatus | undefined {
    const id = this.byIdempotency.get(key);
    if (!id) return undefined;
    const cmd = this.commands.get(id);
    if (!cmd) return undefined;
    return isTerminal(cmd.state) ? undefined : cmd;
  }

  create(commandId: string, request: RuntimeCommandRequest): RuntimeCommandStatus {
    const now = new Date().toISOString();
    const status: RuntimeCommandStatus = {
      commandId,
      clientRequestId: request.clientRequestId,
      correlationId: request.correlationId,
      idempotencyKey: request.idempotencyKey,
      kind: request.kind,
      targetId: request.targetId,
      state: "SUBMITTING",
      reason: request.reason,
      createdAt: now,
      updatedAt: now,
    };
    this.commands.set(commandId, status);
    this.byIdempotency.set(request.idempotencyKey, commandId);
    this.trim();
    this.emit();
    return status;
  }

  update(commandId: string, patch: Partial<RuntimeCommandStatus>) {
    const existing = this.commands.get(commandId);
    if (!existing) return;
    const nextState = patch.state ?? existing.state;
    if (patch.state && patch.state !== existing.state) {
      const check = validateTransition(existing.state, patch.state);
      if (!check.ok) {
        emitInvalidTransition(existing, patch.state, check.reason ?? "invalid");
        return;
      }
    }
    const updated: RuntimeCommandStatus = {
      ...existing,
      ...patch,
      updatedAt: new Date().toISOString(),
    };
    if (isTerminal(updated.state) && !updated.completedAt) {
      updated.completedAt = updated.updatedAt;
    }
    this.commands.set(commandId, updated);
    // Phase 5E: entering EXECUTION_UNKNOWN auto-acquires the entity lock.
    if (nextState === "EXECUTION_UNKNOWN" && existing.state !== "EXECUTION_UNKNOWN") {
      executionUnknownLocks.acquire({
        commandId: updated.commandId,
        kind: updated.kind,
        targetId: updated.targetId,
        correlationId: updated.correlationId,
        operation: operationFor(updated.kind),
      });
    }
    this.emit();
  }

  get(commandId: string): RuntimeCommandStatus | undefined {
    return this.commands.get(commandId);
  }

  list(): RuntimeCommandStatus[] {
    return this.listCache;
  }

  counts() {
    return this.countsCache;
  }

  private trim() {
    if (this.commands.size <= MAX_HISTORY) return;
    // Drop oldest terminal commands.
    const sorted = Array.from(this.commands.values()).sort(
      (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
    );
    for (const c of sorted) {
      if (this.commands.size <= MAX_HISTORY) break;
      if (isTerminal(c.state)) {
        this.commands.delete(c.commandId);
        this.byIdempotency.delete(c.idempotencyKey);
      }
    }
  }
}

export function isTerminal(state: RuntimeCommandStatus["state"]): boolean {
  return (
    state === "COMPLETED" ||
    state === "FAILED" ||
    state === "TIMED_OUT" ||
    state === "EXECUTION_UNKNOWN" ||
    state === "CANCELLED"
  );
}

export const commandStore = new CommandStore();

/** Build a fresh command request with UUIDs. */
export function makeRequest(
  kind: RuntimeCommandKind,
  opts: {
    targetId?: string;
    reason?: string;
    parameters?: Record<string, unknown>;
    expectedRevision?: number;
    idempotencyKey?: string;
  } = {},
): RuntimeCommandRequest {
  const uid = safeUuid();
  return {
    clientRequestId: `req_${uid}`,
    idempotencyKey: opts.idempotencyKey ?? `${kind}:${opts.targetId ?? "-"}:${uid}`,
    correlationId: `corr_${uid}`,
    kind,
    targetId: opts.targetId,
    reason: opts.reason,
    parameters: opts.parameters,
    expectedRevision: opts.expectedRevision,
    submittedAt: new Date().toISOString(),
  };
}

function safeUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function operationFor(kind: RuntimeCommandKind) {
  if (kind.startsWith("position.management.")) return "MANAGEMENT" as const;
  if (kind.startsWith("position.close")) return "CLOSE" as const;
  if (kind === "position.modifyProtection") return "PROTECTION" as const;
  if (kind === "order.cancel" || kind === "order.cancelAll") return "CANCEL" as const;
  if (kind === "runtime.emergencyKill") return "KILL_STEP" as const;
  if (kind.startsWith("order.")) return "SUBMIT" as const;
  return "OTHER" as const;
}

function emitInvalidTransition(
  existing: RuntimeCommandStatus,
  attempted: RuntimeCommandStatus["state"],
  reason: string,
) {
  // Lazy import to avoid a module cycle with the events pipeline.
  void import("./events/event-store").then(({ eventHistoryStore }) => {
    const now = new Date().toISOString();
    eventHistoryStore.push({
      eventId: `sys-cmd-invalid-${existing.commandId}-${Date.now().toString(36)}`,
      type: "system.validation.failed",
      runtimeId: "xdirga-runtime-frontend",
      bootId: "frontend",
      revision: 0,
      sequence: 0,
      occurredAt: now,
      emittedAt: now,
      receivedAt: now,
      severity: "ERROR",
      source: "DEVELOPMENT_FIXTURE",
      commandId: existing.commandId,
      correlationId: existing.correlationId,
      payload: {
        scope: "command.transition",
        commandId: existing.commandId,
        kind: existing.kind,
        from: existing.state,
        to: attempted,
        reason,
      },
    });
  });
}
