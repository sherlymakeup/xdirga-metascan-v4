// Single source of truth for the XDIRGA METASCAN → XDirga Runtime V4 contract.
//
// This file centralizes the values that the frontend expects from the backend
// so no component or adapter re-declares them locally.
//
// IMPORTANT semantics:
//   - FrontendDataSource describes where the UI is reading data FROM
//     (development fixture vs. the local runtime). It is NOT a trading mode.
//   - BrokerEnvironment ("TRIAL" | "LIVE") describes the target broker account
//     environment. It is metadata about the *target*, not proof of a connection.
//   - ExecutionSemantics is always "LIVE": commands are treated with LIVE-grade
//     safety even when the current data source is a fixture.
//
// The frontend is pinned at build time to the backend's existing canonical
// contract hash and independently validates it during the handshake.

import type { RuntimeCommandKind } from "./runtime-types";

export const RUNTIME_CONTRACT = {
  protocolId: "xdirga-runtime-v4",
  // Phase 5F.5 — bumped to 4.1 for management + journal contract additions.
  protocolVersion: "4.1.0",
  schemaVersion: "1.1.0",
  schemaHash: "98b19002044177c883b1a8ecc08f56349e3f6637399a77f0da115b5e8f77fe12",
  minRuntimeVersion: "4.1.0",
  minFrontendVersion: "1.0.0",
  frontendVersion: "1.1.0",
} as const;

const SAFETY_CRITICAL_COMMANDS: readonly RuntimeCommandKind[] = [
  "runtime.emergencyKill",
  "runtime.pause",
  "runtime.disableEntries",
  "order.cancelAll",
  "position.closeAll",
];

const REQUIRED_COMMANDS: readonly RuntimeCommandKind[] = [
  ...SAFETY_CRITICAL_COMMANDS,
  "runtime.start",
  "runtime.resume",
  "runtime.reconnectBroker",
  "runtime.reconcile",
  "strategy.pause",
  "strategy.resume",
  "order.cancel",
  "position.close",
  "position.management.pause",
  "position.management.resume",
  "breaker.reset",
  "config.validate",
  "config.apply",
  "config.rollback",
];

const REQUIRED_FEATURES: readonly string[] = [
  "runtime.capabilities",
  "runtime.commands",
  "runtime.events",
  "runtime.reconciliation",
  "runtime.safety",
  "position.management",
  "trade.history",
];

export const EXPECTED_RUNTIME_CONTRACT = {
  runtimeName: "XDirga Runtime V4",
  protocolId: RUNTIME_CONTRACT.protocolId,
  protocolVersion: RUNTIME_CONTRACT.protocolVersion,
  schemaVersion: RUNTIME_CONTRACT.schemaVersion,
  schemaHash: RUNTIME_CONTRACT.schemaHash,
  minRuntimeVersion: RUNTIME_CONTRACT.minRuntimeVersion,

  brokerProvider: "EXNESS",
  brokerEnvironment: "TRIAL",
  executionSemantics: "LIVE",

  requiredFeatures: REQUIRED_FEATURES,
  requiredCommands: REQUIRED_COMMANDS,
  safetyCriticalCommands: SAFETY_CRITICAL_COMMANDS,
} as const;
