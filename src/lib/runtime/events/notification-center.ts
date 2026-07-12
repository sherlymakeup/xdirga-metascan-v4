// Persistent notification center — bounded, filterable, per-notification
// occurrence counter with dedupe.

import { useSyncExternalStore } from "react";
import type { RuntimeEventEnvelope } from "./event-types";
import type { EventNotificationDecision } from "./notification-policy";

const MAX_ENTRIES = 200;

export interface NotificationEntry {
  id: string;
  firstSeenAt: string;
  lastSeenAt: string;
  count: number;
  acknowledged: boolean;
  acknowledgedAt?: string;
  latest: RuntimeEventEnvelope;
  decision: EventNotificationDecision;
}

type Listener = () => void;

class NotificationCenterStore {
  private entries = new Map<string, NotificationEntry>();
  private order: string[] = []; // most recent first
  private listeners = new Set<Listener>();
  private listCache: NotificationEntry[] = [];
  private countsCache = {
    critical: 0,
    warning: 0,
    unread: 0,
    acknowledged: 0,
    fixture: 0,
    total: 0,
  };

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private recompute() {
    this.listCache = this.order
      .map((id) => this.entries.get(id))
      .filter((e): e is NotificationEntry => Boolean(e));
    let critical = 0,
      warning = 0,
      unread = 0,
      acknowledged = 0,
      fixture = 0;
    for (const e of this.entries.values()) {
      if (e.decision.priority === "CRITICAL") critical += 1;
      else if (e.latest.severity === "WARNING" || e.latest.severity === "ERROR") warning += 1;
      if (!e.acknowledged) unread += 1;
      else acknowledged += 1;
      if (e.latest.source === "DEVELOPMENT_FIXTURE") fixture += 1;
    }
    this.countsCache = {
      critical,
      warning,
      unread,
      acknowledged,
      fixture,
      total: this.entries.size,
    };
  }

  private emit() {
    this.recompute();
    for (const l of this.listeners) l();
  }

  ingest(env: RuntimeEventEnvelope, decision: EventNotificationDecision) {
    if (!decision.persistInNotificationCenter) return;
    const key = decision.dedupeKey ?? env.eventId;
    const existing = this.entries.get(key);
    const now = env.receivedAt || new Date().toISOString();
    if (existing) {
      existing.count += 1;
      existing.lastSeenAt = now;
      existing.latest = env;
      if (env.severity === "CRITICAL" && existing.decision.priority !== "CRITICAL") {
        existing.acknowledged = false;
      }
      existing.decision = decision;
      this.order = this.order.filter((k) => k !== key);
      this.order.unshift(key);
    } else {
      this.entries.set(key, {
        id: key,
        firstSeenAt: now,
        lastSeenAt: now,
        count: 1,
        acknowledged: false,
        latest: env,
        decision,
      });
      this.order.unshift(key);
      if (this.order.length > MAX_ENTRIES) {
        const drop = this.order.pop();
        if (drop) this.entries.delete(drop);
      }
    }
    this.emit();
  }

  acknowledge(id: string) {
    const entry = this.entries.get(id);
    if (!entry || entry.acknowledged) return;
    entry.acknowledged = true;
    entry.acknowledgedAt = new Date().toISOString();
    this.emit();
  }

  acknowledgeAll() {
    let changed = false;
    for (const e of this.entries.values()) {
      if (!e.acknowledged) {
        e.acknowledged = true;
        e.acknowledgedAt = new Date().toISOString();
        changed = true;
      }
    }
    if (changed) this.emit();
  }

  clear() {
    this.entries.clear();
    this.order = [];
    this.emit();
  }

  list = (): NotificationEntry[] => this.listCache;

  counts = () => this.countsCache;
}

export const notificationCenter = new NotificationCenterStore();

const EMPTY_LIST: NotificationEntry[] = [];
const EMPTY_COUNTS = {
  critical: 0,
  warning: 0,
  unread: 0,
  acknowledged: 0,
  fixture: 0,
  total: 0,
};

export function useNotifications(): NotificationEntry[] {
  return useSyncExternalStore(
    notificationCenter.subscribe,
    () => notificationCenter.list(),
    () => EMPTY_LIST,
  );
}

export function useNotificationCounts() {
  return useSyncExternalStore(
    notificationCenter.subscribe,
    () => notificationCenter.counts(),
    () => EMPTY_COUNTS,
  );
}

