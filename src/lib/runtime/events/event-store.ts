// Bounded frontend event history — survives route changes.
// Uses external-store pattern (compatible with useSyncExternalStore).

import { useSyncExternalStore } from "react";
import type { RuntimeEventEnvelope, RuntimeEventType, EventSeverity } from "./event-types";

const MAX_EVENTS = 1000;
const MAX_PINNED = 100;

type Listener = () => void;

export interface EventFilter {
  severities?: EventSeverity[];
  types?: RuntimeEventType[];
  sources?: Array<"DEVELOPMENT_FIXTURE" | "LOCAL_RUNTIME">;
  correlationId?: string;
  commandId?: string;
  orderId?: string;
  positionId?: string;
  incidentId?: string;
  search?: string;
  fixtureOnly?: boolean;
}

class EventHistoryStore {
  private events: RuntimeEventEnvelope[] = [];
  private pinned = new Set<string>();
  private paused = false;
  private pendingWhilePaused: RuntimeEventEnvelope[] = [];
  private listeners = new Set<Listener>();
  private pausedSnapshot: { paused: boolean; pending: number } = { paused: false, pending: 0 };

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private emit() {
    this.pausedSnapshot = { paused: this.paused, pending: this.pendingWhilePaused.length };
    for (const l of this.listeners) l();
  }

  push(env: RuntimeEventEnvelope) {
    if (this.paused) {
      this.pendingWhilePaused.push(env);
      if (this.pendingWhilePaused.length > MAX_EVENTS) {
        this.pendingWhilePaused.shift();
      }
      this.emit();
      return;
    }
    this.events.unshift(env);
    if (this.events.length > MAX_EVENTS) this.events.length = MAX_EVENTS;
    this.emit();
  }

  setPaused(next: boolean) {
    if (next === this.paused) return;
    this.paused = next;
    if (!next && this.pendingWhilePaused.length) {
      // Prepend buffered events in chronological order (newest first overall).
      const buffered = this.pendingWhilePaused.splice(0);
      this.events = [...buffered.reverse(), ...this.events].slice(0, MAX_EVENTS);
    }
    this.emit();
  }

  isPaused = () => this.paused;
  pendingCount = () => this.pendingWhilePaused.length;
  getPausedSnapshot = () => this.pausedSnapshot;

  pin(id: string) {
    if (this.pinned.size >= MAX_PINNED) return;
    this.pinned.add(id);
    this.emit();
  }
  unpin(id: string) {
    this.pinned.delete(id);
    this.emit();
  }
  isPinned = (id: string) => this.pinned.has(id);

  list = (): RuntimeEventEnvelope[] => this.events;
  filtered(filter: EventFilter): RuntimeEventEnvelope[] {
    const s = filter.search?.toLowerCase();
    return this.events.filter((e) => {
      if (filter.severities?.length && !filter.severities.includes(e.severity)) return false;
      if (filter.types?.length && !filter.types.includes(e.type)) return false;
      if (filter.sources?.length && !filter.sources.includes(e.source)) return false;
      if (filter.fixtureOnly && e.source !== "DEVELOPMENT_FIXTURE") return false;
      if (filter.correlationId && e.correlationId !== filter.correlationId) return false;
      if (filter.commandId && e.commandId !== filter.commandId) return false;
      if (filter.orderId && e.orderId !== filter.orderId) return false;
      if (filter.positionId && e.positionId !== filter.positionId) return false;
      if (filter.incidentId && e.incidentId !== filter.incidentId) return false;
      if (s) {
        const hay = `${e.type} ${e.severity} ${JSON.stringify(e.payload ?? {})}`.toLowerCase();
        if (!hay.includes(s)) return false;
      }
      return true;
    });
  }

  clear() {
    this.events = [];
    this.pendingWhilePaused = [];
    this.emit();
  }
}

const INITIAL_PAUSED = { paused: false, pending: 0 };

export const eventHistoryStore = new EventHistoryStore();

export function useEventHistory(): RuntimeEventEnvelope[] {
  return useSyncExternalStore(
    eventHistoryStore.subscribe,
    () => eventHistoryStore.list(),
    () => [],
  );
}

export function useEventHistoryPaused(): { paused: boolean; pending: number } {
  return useSyncExternalStore(
    eventHistoryStore.subscribe,
    () => eventHistoryStore.getPausedSnapshot(),
    () => INITIAL_PAUSED,
  );
}
