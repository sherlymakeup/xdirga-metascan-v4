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
  supersededBootIds: Set<string>;
  supersededBootIdsOrder: string[];
}

const MAX_SEEN_IDS = 2000;
// 32 covers normal restart history while keeping per-runtime memory strictly bounded.
const MAX_SUPERSEDED_BOOTS = 32;

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
        supersededBootIds: new Set(),
        supersededBootIdsOrder: [],
      };
      this.cursors.set(key, cursor);
      return { action: "accept" };
    }

    // Boot ID changed — treat as safe reset (do not silently reorder).
    if (env.bootId !== cursor.bootId) {
      if (cursor.supersededBootIds.has(env.bootId)) {
        return { action: "drop", reason: "obsolete-boot" };
      }
      const previous = cursor.bootId;
      this.trackSupersededBoot(cursor, previous);
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
    const previous = this.cursors.get(runtimeId);
    const supersededBootIds = previous?.supersededBootIds ?? new Set<string>();
    const supersededBootIdsOrder = previous?.supersededBootIdsOrder ?? [];
    if (previous && previous.bootId !== bootId) {
      this.trackSupersededBoot(previous, previous.bootId);
    }
    this.cursors.set(runtimeId, {
      runtimeId,
      bootId,
      lastSequence: sequence,
      seenIds: new Set(),
      seenIdsOrder: [],
      supersededBootIds,
      supersededBootIdsOrder,
    });
  }

  private trackSupersededBoot(cursor: RuntimeCursor, bootId: string) {
    if (cursor.supersededBootIds.has(bootId)) return;
    cursor.supersededBootIds.add(bootId);
    cursor.supersededBootIdsOrder.push(bootId);
    if (cursor.supersededBootIdsOrder.length > MAX_SUPERSEDED_BOOTS) {
      const oldest = cursor.supersededBootIdsOrder.shift();
      if (oldest) cursor.supersededBootIds.delete(oldest);
    }
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
