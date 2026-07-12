// HTTP + SSE adapter — typed placeholder. Awaiting the local XDirga Runtime V4
// backend. Transport is intentionally locked to REST + Server-Sent Events for
// v4.1 (see HANDOFF.md §"Transport"). WebSockets are NOT part of the contract.
//
// Auth model (see HANDOFF.md §"Auth"):
//  * REST — Bearer token via `Authorization: Bearer <token>` header.
//  * SSE  — `EventSource` cannot set headers, so the token MUST be sent as a
//    `?token=<token>` query parameter on the stream URL. The backend accepts
//    BOTH header (REST) and query (SSE only) auth on the same identity.
//
// Safe-fail contract:
//  * Read paths (getSnapshot / getSnapshotEnvelope / getCapabilities /
//    getConnectionState / getTradeHistory) MUST NOT throw. They return an
//    empty, disconnected view so panels never crash the tree.
//  * Write / async paths reject with NotImplementedError. There is
//    intentionally NO silent fallback to fixture data.

import type { RuntimeAdapter } from "./runtime-adapter";
import { NotImplementedError } from "./runtime-types";
import { RUNTIME_CONTRACT } from "./runtime-contract";
import { buildCapabilities } from "./runtime-capabilities";
import { createEmptySnapshot } from "@/lib/demo/scenarios";
import type {
  CommandAccepted,
  OperatorIdentity,
  RuntimeAdapterDescriptor,
  RuntimeCapabilities,
  RuntimeCommandRequest,
  RuntimeCommandStatus,
  RuntimeConnectionStateSnapshot,
  RuntimeEventEnvelope,
  RuntimeHandshake,
  RuntimeSnapshotEnvelope,
} from "./runtime-types";
import type { CockpitSnapshot, TradeHistoryPage, TradeHistoryQuery } from "@/lib/types";

export interface HttpAdapterConfig {
  /** REST base URL, e.g. http://127.0.0.1:8787/v4 */
  baseUrl: string;
  /**
   * SSE stream path relative to baseUrl. Backend MUST accept the auth token
   * as `?token=<token>` because EventSource cannot set custom headers.
   * Default: "/events/stream".
   */
  eventStreamPath?: string;
  /**
   * Bearer token. Sent as `Authorization: Bearer <token>` for REST and as
   * `?token=<token>` on the SSE URL.
   */
  authToken?: string;
}

/** Stub. Real implementation lives with the local runtime integration. */
export class HttpRuntimeAdapter implements RuntimeAdapter {
  readonly adapterType = "http" as const;

  constructor(_config: HttpAdapterConfig) {
    void _config;
  }

  connect(): Promise<void> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.connect"));
  }
  disconnect(): Promise<void> {
    return Promise.resolve();
  }
  getSnapshot(): CockpitSnapshot {
    return createEmptySnapshot();
  }
  getSnapshotEnvelope(): RuntimeSnapshotEnvelope {
    const t = new Date().toISOString();
    return {
      metadata: {
        runtimeId: "rt_disconnected",
        bootId: "boot_disconnected",
        revision: 0,
        sequence: 0,
        generatedAt: t,
        serverTimestamp: t,
        protocolId: RUNTIME_CONTRACT.protocolId,
        protocolVersion: RUNTIME_CONTRACT.protocolVersion,
        schemaVersion: RUNTIME_CONTRACT.schemaVersion,
        schemaHash: RUNTIME_CONTRACT.schemaHash,
        source: "LOCAL_RUNTIME",
      },
      snapshot: createEmptySnapshot(),
    };
  }
  refreshSnapshot(): Promise<RuntimeSnapshotEnvelope> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.refreshSnapshot"));
  }
  subscribeSnapshot(_l: (env: RuntimeSnapshotEnvelope) => void): () => void {
    void _l;
    return () => {};
  }
  subscribeEvents(_l: (env: RuntimeEventEnvelope) => void): () => void {
    void _l;
    return () => {};
  }
  getCapabilities(): RuntimeCapabilities {
    // Safe-fail: return capabilities with every command disallowed. UI reads
    // .allowed and .reason for its own gating — no throw at render time.
    const caps = buildCapabilities(createEmptySnapshot(), "LOCAL_RUNTIME");
    const disabled: RuntimeCapabilities = {
      ...caps,
      commands: Object.fromEntries(
        Object.entries(caps.commands).map(([k, cap]) => [
          k,
          { ...cap, allowed: false, reason: "No local runtime connected." },
        ]),
      ) as RuntimeCapabilities["commands"],
    };
    return disabled;
  }
  refreshCapabilities(): Promise<RuntimeCapabilities> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.refreshCapabilities"));
  }
  getHandshake(): RuntimeHandshake | null {
    return null;
  }
  refreshHandshake(): Promise<RuntimeHandshake> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.refreshHandshake"));
  }
  subscribeHandshake(_l: (h: RuntimeHandshake | null) => void): () => void {
    void _l;
    return () => {};
  }
  submitCommand(_r: RuntimeCommandRequest): Promise<CommandAccepted> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.submitCommand"));
  }
  getCommand(_id: string): Promise<RuntimeCommandStatus> {
    return Promise.reject(new NotImplementedError("HttpRuntimeAdapter.getCommand"));
  }
  subscribeCommand(_id: string, _l: (s: RuntimeCommandStatus) => void): () => void {
    return () => {};
  }
  getTradeHistory(_q?: TradeHistoryQuery): Promise<TradeHistoryPage> {
    // Safe-fail read: return empty page rather than throw so the Journal UI
    // can render an empty state while the local runtime is not connected.
    return Promise.resolve({ trades: [], nextCursor: null });
  }
  getConnectionState(): RuntimeConnectionStateSnapshot {
    return {
      state: "DISCONNECTED",
      mode: "LOCAL_RUNTIME",
      adapterType: "http",
      reconnectAttempt: 0,
      errorMessage:
        "No local runtime connected. Start the local XDirga Runtime V4 and set VITE_RUNTIME_BASE_URL to connect. Target broker: Exness TRIAL.",
    };
  }
  subscribeConnection(_l: (s: RuntimeConnectionStateSnapshot) => void): () => void {
    return () => {};
  }

  getOperator(): OperatorIdentity {
    // Safe-fail: while the local runtime is not connected there is no
    // authenticated operator. Return a deterministic VIEWER identity so
    // hooks (`useOperator`, `useRoleCanRun`) do not throw during render.
    // Every capability is also `allowed:false` via getCapabilities(), so
    // no command can slip through even if a UI ignores the role gate.
    const t = "1970-01-01T00:00:00.000Z";
    return {
      operatorId: "op_disconnected",
      displayName: "Disconnected",
      role: "VIEWER",
      sessionId: "sess_disconnected",
      authenticatedAt: t,
      simulated: false,
    };
  }

  getDescriptor(): RuntimeAdapterDescriptor {
    return {
      adapterType: "HTTP_LOCAL_RUNTIME",
      dataSource: "LOCAL_RUNTIME",
      isDevelopmentOnly: false,
    };
  }
  isDevelopmentFixture(): boolean {
    return false;
  }
  /** @deprecated Use isDevelopmentFixture(). */
  isDemo(): boolean {
    return false;
  }
}

