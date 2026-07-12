// DEPRECATED entry point — retained for backwards compatibility.
// The authoritative envelope + catalog now live in ./runtime-event-envelope.
// Import from `@/lib/runtime/events` (which re-exports both).

export {
  RUNTIME_EVENT_TYPES,
  SEVERITY_ORDER,
  runtimeEventTypeSchema,
  eventSeveritySchema,
  frontendDataSourceSchema,
} from "./runtime-event-envelope";
export type {
  EventSeverity,
  RuntimeEventType,
  RuntimeEventEnvelope,
  EventSourceState,
} from "./runtime-event-envelope";
