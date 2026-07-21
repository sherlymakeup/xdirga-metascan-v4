// Broker environment surfacing — centralized target metadata, observed state,
// and a derived view-model used across every page and confirmation dialog.
//
// Rules (Phase 5B):
//   - Target metadata is CONFIGURATION. It never implies connectivity.
//   - Broker connection is OBSERVED runtime data. Fixture-derived values must
//     be marked as such and must not claim a real Exness/MT5 session exists.
//   - Local runtime connection is separate from broker connection.
//   - Execution semantics stay LIVE-grade even when the target account is TRIAL.

import { useMemo } from "react";
import { useConnectionState, useSnapshot, getRuntimeAdapter } from "./index";
import type {
  BrokerEnvironment,
  BrokerTargetMetadata,
  ExecutionSemantics,
  FrontendDataSource,
} from "./runtime-types";

// -----------------------------------------------------------------------------
// Immutable target metadata (Phase 5B — no operator-facing switcher).
// -----------------------------------------------------------------------------

export const BROKER_TARGET: BrokerTargetMetadata = Object.freeze({
  provider: "EXNESS",
  environment: "TRIAL",
  executionSemantics: "LIVE",
});

// -----------------------------------------------------------------------------
// Observed connection state — kept distinct from target metadata.
// -----------------------------------------------------------------------------

export type LocalRuntimeConnectionState =
  | "NOT_CONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "RECONNECTING"
  | "STALE"
  | "ERROR";

export type BrokerConnectionState =
  | "DISCONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "RECONNECTING"
  | "DEGRADED"
  | "ERROR"
  | "UNKNOWN";

export interface BrokerConnectionView {
  state: BrokerConnectionState;
  serverName?: string;
  accountIdMasked?: string;
  accountType?: BrokerEnvironment;
  tradingPermission?: boolean;
  terminalConnected?: boolean;
  lastHeartbeatAt?: string | null;
  lastSuccessfulRequestAt?: string | null;
  latencyMs?: number;
  reconnectAttempts?: number;
  errorCode?: string;
  errorMessage?: string;
  source: FrontendDataSource;
}

// -----------------------------------------------------------------------------
// Reusable view model
// -----------------------------------------------------------------------------

export interface BrokerEnvironmentViewModel {
  target: BrokerTargetMetadata;
  providerLabel: string;
  environmentLabel: string;
  executionSemanticsLabel: string;

  frontendDataSource: FrontendDataSource;
  localRuntimeConnection: LocalRuntimeConnectionState;
  broker: BrokerConnectionView;

  isFixtureDerived: boolean;
  isAuthoritative: boolean;

  tradingPermissionKnown: boolean;
  tradingPermissionEnabled?: boolean;

  dataFreshness?: string;
  lastBrokerHeartbeatAt?: string | null;
  lastBrokerRequestAt?: string | null;

  warning?: string;
}

export function useBrokerEnvironment(): BrokerEnvironmentViewModel {
  const snap = useSnapshot();
  const conn = useConnectionState();
  const adapter = getRuntimeAdapter();

  return useMemo<BrokerEnvironmentViewModel>(() => {
    const isFixture = adapter.adapterType === "fixture";
    const frontendDataSource: FrontendDataSource = isFixture
      ? "DEVELOPMENT_FIXTURE"
      : "LOCAL_RUNTIME";

    const localRuntimeConnection: LocalRuntimeConnectionState = isFixture
      ? "NOT_CONNECTED"
      : mapConnToLocal(conn.state);

    const brokerState: BrokerConnectionState = mapBrokerConn(snap.broker.connection);
    const broker: BrokerConnectionView = {
      state: brokerState,
      serverName: snap.broker.server,
      accountIdMasked: snap.broker.loginMasked,
      accountType: snap.broker.accountMode,
      tradingPermission: snap.broker.tradingPermitted,
      terminalConnected: brokerState === "CONNECTED",
      lastHeartbeatAt: snap.broker.lastTickAt,
      lastSuccessfulRequestAt: snap.broker.lastRequestAt,
      latencyMs: snap.broker.avgLatencyMs ?? undefined,
      reconnectAttempts: snap.broker.reconnectAttempts,
      source: frontendDataSource,
    };

    return {
      target: BROKER_TARGET,
      providerLabel: "Exness",
      environmentLabel: BROKER_TARGET.environment === "TRIAL" ? "Trial" : "Live",
      executionSemanticsLabel: "Live-Grade",
      frontendDataSource,
      localRuntimeConnection,
      broker,
      isFixtureDerived: isFixture,
      isAuthoritative: !isFixture,
      tradingPermissionKnown: !isFixture,
      tradingPermissionEnabled: !isFixture ? snap.broker.tradingPermitted : undefined,
      dataFreshness: snap.account.freshness,
      lastBrokerHeartbeatAt: snap.broker.lastTickAt,
      lastBrokerRequestAt: snap.broker.lastRequestAt,
      warning: isFixture
        ? "Fixture-derived. No real broker, MT5 terminal, or local runtime is connected."
        : undefined,
    };
  }, [snap, conn, adapter]);
}

function mapConnToLocal(state: string): LocalRuntimeConnectionState {
  switch (state) {
    case "CONNECTED":
      return "CONNECTED";
    case "CONNECTING":
      return "CONNECTING";
    case "RECONNECTING":
      return "RECONNECTING";
    case "STALE":
      return "STALE";
    case "ERROR":
      return "ERROR";
    default:
      return "NOT_CONNECTED";
  }
}

function mapBrokerConn(s: string): BrokerConnectionState {
  switch (s) {
    case "CONNECTED":
      return "CONNECTED";
    case "DISCONNECTED":
      return "DISCONNECTED";
    case "RECONNECTING":
      return "RECONNECTING";
    case "DEGRADED":
      return "DEGRADED";
    case "UNKNOWN":
      return "UNKNOWN";
    default:
      return "UNKNOWN";
  }
}
