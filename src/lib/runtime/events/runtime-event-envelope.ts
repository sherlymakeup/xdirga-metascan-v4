// Authoritative runtime event envelope + event type catalog.
//
// This module is the SINGLE source of truth for:
//   * the envelope shape (RuntimeEventEnvelope)
//   * the allowed event type strings (RUNTIME_EVENT_TYPES)
//   * the derived type union (RuntimeEventType)
//   * the runtime validator (runtimeEventTypeSchema)
//
// Every adapter, router, store, page, and test MUST import from this file.
// Older locations (`./event-types`, `../runtime-types`) re-export these
// symbols for backwards compatibility only.

import { z } from "zod";
import type { FrontendDataSource } from "../runtime-types";

// -----------------------------------------------------------------------------
// Severity
// -----------------------------------------------------------------------------

export type EventSeverity =
  | "TRACE"
  | "DEBUG"
  | "INFO"
  | "WARNING"
  | "ERROR"
  | "CRITICAL";

export const SEVERITY_ORDER: Record<EventSeverity, number> = {
  TRACE: 0,
  DEBUG: 1,
  INFO: 2,
  WARNING: 3,
  ERROR: 4,
  CRITICAL: 5,
};

// -----------------------------------------------------------------------------
// Authoritative event type catalog
// -----------------------------------------------------------------------------

export const RUNTIME_EVENT_TYPES = [
  "runtime.state.changed",
  "runtime.health.changed",
  "runtime.connection.changed",
  "runtime.handshake.changed",
  "runtime.safe_mode.changed",

  "broker.connection.changed",
  "broker.permission.changed",
  "broker.request.completed",
  "broker.request.failed",

  "command.created",
  "command.accepted",
  "command.acknowledged",
  "command.progress",
  "command.completed",
  "command.failed",
  "command.timed_out",
  "command.execution_unknown",

  "order.created",
  "order.updated",
  "order.partially_filled",
  "order.filled",
  "order.cancelled",
  "order.rejected",
  "order.execution_unknown",

  "position.opened",
  "position.updated",
  "position.protection_changed",
  "position.partially_closed",
  "position.closed",
  "position.unprotected",
  "position.execution_unknown",
  "position.management.plan_changed",
  "position.management.action_executed",
  "position.management.action_failed",

  "trade.closed",


  "strategy.state.changed",
  "strategy.signal.generated",
  "strategy.decision.created",
  "strategy.blocked",

  "risk.evaluation.completed",
  "risk.limit.warning",
  "risk.limit.breached",

  "safety.circuit_breaker.warning",
  "safety.circuit_breaker.opened",
  "safety.circuit_breaker.closed",
  "safety.entries.disabled",
  "safety.entries.enabled",
  "safety.kill.started",
  "safety.kill.progress",
  "safety.kill.completed",
  "safety.kill.failed",

  "reconciliation.started",
  "reconciliation.issue.detected",
  "reconciliation.issue.resolved",
  "reconciliation.completed",
  "reconciliation.failed",

  "alert.created",
  "alert.acknowledged",
  "incident.created",
  "incident.updated",
  "incident.resolved",

  "configuration.validated",
  "configuration.applied",
  "configuration.failed",

  "system.validation.failed",
  "system.event_gap.detected",
] as const;

export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];

export const runtimeEventTypeSchema = z.enum(RUNTIME_EVENT_TYPES);
export const eventSeveritySchema = z.enum([
  "TRACE",
  "DEBUG",
  "INFO",
  "WARNING",
  "ERROR",
  "CRITICAL",
]);
export const frontendDataSourceSchema = z.enum([
  "DEVELOPMENT_FIXTURE",
  "LOCAL_RUNTIME",
]);

// -----------------------------------------------------------------------------
// Envelope
// -----------------------------------------------------------------------------

export interface RuntimeEventEnvelope<T = unknown> {
  eventId: string;
  type: RuntimeEventType;

  runtimeId: string;
  bootId: string;

  revision: number;
  sequence: number;

  occurredAt: string;
  emittedAt: string;
  /** Assigned by the frontend on ingestion. */
  receivedAt: string;

  severity: EventSeverity;
  source: FrontendDataSource;

  correlationId?: string;
  commandId?: string;
  orderId?: string;
  positionId?: string;
  strategyId?: string;
  incidentId?: string;
  reconciliationRunId?: string;

  payload: T;
}

export type EventSourceState =
  | "STOPPED"
  | "STARTING"
  | "RUNNING"
  | "RECONNECTING"
  | "STALE"
  | "ERROR";
