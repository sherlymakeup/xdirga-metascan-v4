// Deduplication + ordering + boot-id + sequence-gap detection.
// Pure — safe to unit-test in isolation.

import type { RuntimeEventEnvelope } from "./event-types";

export type DedupOutcome =
  | { action: "accept" }
  | { action: "gap"; missing: number; from: number; to: number }
  | { action: "reset-boot"; previousBootId: string; newBootId: string }
  | {
      action: "drop";
      reason: "duplicate-id" | "duplicate-sequence" | "older-sequence" | "obsolete-boot";
    };

interface RuntimeCursor {
  runtimeId: string;
  bootId: string;
  lastSequence: number;
  seenIds: Set<string>;
  seenIdsOrder: string[];
}

const MAX_SEEN_IDS = 2000;

export class EventDeduplicator {
  private cursors = new Map<string, RuntimeCursor>();

  evaluate(env: RuntimeEventEnvelope): DedupOutcome {
    const key = env.runtimeId;
    let cursor = this.cursors.get(key);

    if (!cursor) {
      cursor = {
        runtimeId: env.runtimeId,
        bootId: env.bootId,
        lastSequence: env.sequence,
        seenIds: new Set([env.eventId]),
        seenIdsOrder: [env.eventId],
      };
      this.cursors.set(key, cursor);
      return { action: "accept" };
    }

    // Boot ID changed — treat as safe reset (do not silently reorder).
    if (env.bootId !== cursor.bootId) {
      // Compare boot ordering by lexical string only when both look ISO-ish; otherwise
      // trust the new boot ID as authoritative (runtime restarted).
      const previous = cursor.bootId;
      if (env.bootId < previous) {
        return { action: "drop", reason: "obsolete-boot" };
      }
      cursor.bootId = env.bootId;
      cursor.lastSequence = env.sequence;
      cursor.seenIds = new Set([env.eventId]);
      cursor.seenIdsOrder = [env.eventId];
      return { action: "reset-boot", previousBootId: previous, newBootId: env.bootId };
    }

    if (cursor.seenIds.has(env.eventId)) {
      return { action: "drop", reason: "duplicate-id" };
    }

    if (env.sequence < cursor.lastSequence) {
      return { action: "drop", reason: "older-sequence" };
    }
    if (env.sequence === cursor.lastSequence) {
      // Same sequence but different eventId — treat as duplicate ordering slot.
      this.trackId(cursor, env.eventId);
      return { action: "drop", reason: "duplicate-sequence" };
    }

    const expected = cursor.lastSequence + 1;
    if (env.sequence > expected) {
      const gap: DedupOutcome = {
        action: "gap",
        missing: env.sequence - expected,
        from: expected,
        to: env.sequence - 1,
      };
      cursor.lastSequence = env.sequence;
      this.trackId(cursor, env.eventId);
      return gap;
    }

    cursor.lastSequence = env.sequence;
    this.trackId(cursor, env.eventId);
    return { action: "accept" };
  }

  reset(): void {
    this.cursors.clear();
  }

  resetToSnapshot(runtimeId: string, bootId: string, sequence: number): void {
    this.cursors.set(runtimeId, {
      runtimeId,
      bootId,
      lastSequence: sequence,
      seenIds: new Set(),
      seenIdsOrder: [],
    });
  }

  private trackId(cursor: RuntimeCursor, id: string) {
    cursor.seenIds.add(id);
    cursor.seenIdsOrder.push(id);
    if (cursor.seenIdsOrder.length > MAX_SEEN_IDS) {
      const drop = cursor.seenIdsOrder.shift();
      if (drop) cursor.seenIds.delete(drop);
    }
  }
}
