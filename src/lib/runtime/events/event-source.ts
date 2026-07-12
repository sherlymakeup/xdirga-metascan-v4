// Event source contract + placeholders for future transports.
//
// Transport surface is REST + SSE only (v4.1). The WebSocket placeholder was
// removed intentionally — see HANDOFF.md §10.

import type { RuntimeEventEnvelope, EventSourceState } from "./event-types";

export interface RuntimeEventSource {
  readonly kind: "fixture" | "sse";
  start(): Promise<void>;
  stop(): Promise<void>;
  subscribe(listener: (event: RuntimeEventEnvelope) => void): () => void;
  getState(): EventSourceState;
}

/**
 * Placeholder — real SSE transport lands with the backend handoff.
 *
 * IMPORTANT: `EventSource` cannot set custom headers, so the auth token MUST
 * travel as a `?token=<token>` query parameter on the stream URL. The backend
 * accepts the SAME token via `Authorization: Bearer` on REST and via
 * `?token=` on SSE only — see HANDOFF.md §10.
 */
export class SseRuntimeEventSource implements RuntimeEventSource {
  readonly kind = "sse" as const;
  constructor(_url: string, _tokenProvider?: () => string | null) {
    throw new Error("SseRuntimeEventSource is not implemented yet (backend handoff).");
  }
  async start() { /* unreachable */ }
  async stop() { /* unreachable */ }
  subscribe() { return () => {}; }
  getState(): EventSourceState { return "STOPPED"; }
}
