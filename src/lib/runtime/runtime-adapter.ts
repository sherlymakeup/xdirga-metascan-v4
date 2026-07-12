// The RuntimeAdapter contract. All frontend data + command access flows through here.
// See development-fixture-adapter (mock-runtime-adapter.ts) for the reference implementation
// used while there is no local runtime.

import type {
  CockpitSnapshot,
  ScenarioKey,
  TradeHistoryPage,
  TradeHistoryQuery,
} from "@/lib/types";
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

export interface RuntimeAdapter {
  connect(): Promise<void>;
  disconnect(): Promise<void>;

  getSnapshot(): CockpitSnapshot;
  getSnapshotEnvelope(): RuntimeSnapshotEnvelope;
  refreshSnapshot(): Promise<RuntimeSnapshotEnvelope>;
  subscribeSnapshot(listener: (envelope: RuntimeSnapshotEnvelope) => void): () => void;

  subscribeEvents(listener: (event: RuntimeEventEnvelope) => void): () => void;

  getHandshake(): RuntimeHandshake | null;
  refreshHandshake(): Promise<RuntimeHandshake>;
  subscribeHandshake(listener: (h: RuntimeHandshake | null) => void): () => void;

  getCapabilities(): RuntimeCapabilities;
  refreshCapabilities(): Promise<RuntimeCapabilities>;

  submitCommand(request: RuntimeCommandRequest): Promise<CommandAccepted>;
  getCommand(commandId: string): Promise<RuntimeCommandStatus>;
  subscribeCommand(commandId: string, listener: (status: RuntimeCommandStatus) => void): () => void;

  /**
   * Paginated closed-trade history (trade journal). Cursor is opaque and
   * server-defined. The journal cache in the frontend dedupes rows returned
   * here against live `trade.closed` events by tradeId (event wins on
   * conflict) — see src/lib/runtime/domain/trade-journal.ts.
   */
  getTradeHistory(query?: TradeHistoryQuery): Promise<TradeHistoryPage>;

  getConnectionState(): RuntimeConnectionStateSnapshot;
  subscribeConnection(listener: (state: RuntimeConnectionStateSnapshot) => void): () => void;

  getOperator(): OperatorIdentity;

  /** Low-level adapter tag. UI should prefer `getDescriptor()`. */
  readonly adapterType: "fixture" | "http";

  /** Structured adapter metadata for UI logic. Replaces `instanceof` checks. */
  getDescriptor(): RuntimeAdapterDescriptor;

  /** True when the current data source is the development fixture. */
  isDevelopmentFixture(): boolean;

  /** @deprecated Use `isDevelopmentFixture()`. */
  isDemo(): boolean;

  // Development-fixture-only controls (undefined on production adapters).
  setScenario?(scenario: ScenarioKey): void;
  getScenario?(): ScenarioKey;
  simulateHandshakeMismatch?(kind: "none" | "minor" | "major"): void;
  getHandshakeMismatch?(): "none" | "minor" | "major";
}
