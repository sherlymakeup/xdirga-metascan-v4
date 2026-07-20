// Phase 5F.5 — gating of position.management.pause/resume commands.
// Covers the pure gating primitives (role, safe-mode/handshake, EU-lock).
// The full orchestrator is exercised elsewhere; this suite locks in the
// autopilot-specific policy so a regression is immediately visible.

import { describe, it, expect, beforeEach } from "vitest";
import { roleAllows, roleBlockReason } from "../state/operator-role";
import { executionUnknownLocks } from "../state/execution-unknown-lock";
import { evaluateHandshake } from "../runtime-handshake";
import { EXPECTED_RUNTIME_CONTRACT } from "../runtime-contract";

const kindsUnderTest = ["position.management.pause", "position.management.resume"] as const;

describe("management commands — role gating", () => {
  it("OPERATOR / RISK_MANAGER / ADMIN can pause and resume autopilot", () => {
    for (const kind of kindsUnderTest) {
      expect(roleAllows("OPERATOR", kind)).toBe(true);
      expect(roleAllows("RISK_MANAGER", kind)).toBe(true);
      expect(roleAllows("ADMIN", kind)).toBe(true);
    }
  });

  it("VIEWER role is blocked with a human-readable reason", () => {
    for (const kind of kindsUnderTest) {
      expect(roleAllows("VIEWER", kind)).toBe(false);
      expect(roleBlockReason("VIEWER", kind)).toBeTruthy();
    }
  });
});

describe("management commands — execution-unknown lock", () => {
  beforeEach(() => executionUnknownLocks.clear());

  it("EU-lock on a management op blocks the same target only", () => {
    executionUnknownLocks.acquire({
      commandId: "cmd-eu",
      kind: "position.management.pause",
      targetId: "pos-42",
      operation: "MANAGEMENT",
    });
    expect(executionUnknownLocks.isBlocked("position.management.pause", "pos-42")).toBeDefined();
    expect(executionUnknownLocks.isBlocked("position.management.resume", "pos-42")).toBeDefined();
    expect(executionUnknownLocks.isBlocked("position.management.pause", "pos-99")).toBeUndefined();
  });

  it("release-by-target frees management locks for that position", () => {
    executionUnknownLocks.acquire({
      commandId: "cmd-eu",
      kind: "position.management.resume",
      targetId: "pos-42",
      operation: "MANAGEMENT",
    });
    const n = executionUnknownLocks.releaseAllForTarget("pos-42");
    expect(n).toBe(1);
    expect(executionUnknownLocks.isBlocked("position.management.resume", "pos-42")).toBeUndefined();
  });
});

describe("management commands — safe-mode / handshake gating", () => {
  it("a compatible handshake does NOT engage safe mode", () => {
    const compat = evaluateHandshake({
      runtimeName: EXPECTED_RUNTIME_CONTRACT.runtimeName,
      runtimeVersion: EXPECTED_RUNTIME_CONTRACT.protocolVersion,
      runtimeId: "rt",
      bootId: "boot-1",
      protocolId: EXPECTED_RUNTIME_CONTRACT.protocolId,
      protocolVersion: EXPECTED_RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: EXPECTED_RUNTIME_CONTRACT.schemaVersion,
      schemaHash: EXPECTED_RUNTIME_CONTRACT.schemaHash,
      capabilitiesRevision: 1,
      minFrontendVersion: "1.0.0",
      supportedFeatures: [...EXPECTED_RUNTIME_CONTRACT.requiredFeatures],
      supportedCommands: [...EXPECTED_RUNTIME_CONTRACT.requiredCommands],
      brokerProvider: EXPECTED_RUNTIME_CONTRACT.brokerProvider,
      brokerEnvironment: EXPECTED_RUNTIME_CONTRACT.brokerEnvironment,
      executionSemantics: EXPECTED_RUNTIME_CONTRACT.executionSemantics,
      source: "LOCAL_RUNTIME",
      observedAt: new Date().toISOString(),
    });
    expect(compat.safeMode).toBe(false);
  });

  it("accepts the pinned backend canonical schema hash", () => {
    expect(EXPECTED_RUNTIME_CONTRACT.schemaHash).toBe(
      "40e05c10e10834573d1151fc7b25fe9556f5ac4a614c910860a6962d84d94cf9",
    );
  });

  it("rejects a runtime-authored hash despite the same schema version", () => {
    const compat = evaluateHandshake({
      runtimeName: EXPECTED_RUNTIME_CONTRACT.runtimeName,
      runtimeVersion: EXPECTED_RUNTIME_CONTRACT.protocolVersion,
      runtimeId: "rt",
      bootId: "boot-1",
      protocolId: EXPECTED_RUNTIME_CONTRACT.protocolId,
      protocolVersion: EXPECTED_RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: EXPECTED_RUNTIME_CONTRACT.schemaVersion,
      schemaHash: "runtime-self-authored-hash",
      capabilitiesRevision: 1,
      supportedFeatures: [...EXPECTED_RUNTIME_CONTRACT.requiredFeatures],
      supportedCommands: [...EXPECTED_RUNTIME_CONTRACT.requiredCommands],
      source: "LOCAL_RUNTIME",
      observedAt: new Date().toISOString(),
    });
    expect(compat.severity).toBe("INCOMPATIBLE");
    expect(compat.safeMode).toBe(true);
    expect(compat.expected.schemaHash).toBe(EXPECTED_RUNTIME_CONTRACT.schemaHash);
    expect(compat.reasons).toContainEqual(
      expect.objectContaining({ code: "SCHEMA_HASH_DRIFT", severity: "INCOMPATIBLE" }),
    );
  });

  it("a null/incompatible handshake engages safe mode (all commands blocked)", () => {
    const compat = evaluateHandshake(null);
    expect(compat.safeMode).toBe(true);
  });
});
