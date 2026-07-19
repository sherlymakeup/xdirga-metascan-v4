// Runtime handshake + schema compatibility evaluator.
//
// Compatibility is *frontend-authored*, not backend-authored: an untrusted
// or downgraded backend cannot silently claim "OK". This evaluator is the
// single source of truth for whether the UI enters SAFE MODE.

import { EXPECTED_RUNTIME_CONTRACT } from "./runtime-contract";
import type {
  HandshakeCompatibility,
  HandshakeReason,
  HandshakeSeverity,
  RuntimeCommandKind,
  RuntimeHandshake,
} from "./runtime-types";

/**
 * Contract the current frontend was compiled against. Bumped whenever the
 * frontend requires a new backend surface.
 */
export const EXPECTED_HANDSHAKE = {
  runtimeName: EXPECTED_RUNTIME_CONTRACT.runtimeName,
  protocolId: EXPECTED_RUNTIME_CONTRACT.protocolId,
  protocolVersion: EXPECTED_RUNTIME_CONTRACT.protocolVersion,
  schemaVersion: EXPECTED_RUNTIME_CONTRACT.schemaVersion,
  schemaHash: EXPECTED_RUNTIME_CONTRACT.schemaHash,
  minRuntimeVersion: EXPECTED_RUNTIME_CONTRACT.minRuntimeVersion,
  requiredCommands: EXPECTED_RUNTIME_CONTRACT.requiredCommands,
  safetyCriticalCommands: EXPECTED_RUNTIME_CONTRACT.safetyCriticalCommands,
  requiredFeatures: EXPECTED_RUNTIME_CONTRACT.requiredFeatures,
} as const;

// -----------------------------------------------------------------------------
// Semver helpers (X.Y.Z; suffixes are stripped)
// -----------------------------------------------------------------------------

function parseSemver(v: string): [number, number, number] | null {
  const m = /^(\d+)\.(\d+)\.(\d+)/.exec(v.trim());
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function cmpSemver(a: string, b: string): number {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  if (!pa || !pb) return pa ? 1 : pb ? -1 : 0;
  for (let i = 0; i < 3; i += 1) {
    if (pa[i] !== pb[i]) return pa[i] > pb[i] ? 1 : -1;
  }
  return 0;
}

const worstSeverity = (a: HandshakeSeverity, b: HandshakeSeverity): HandshakeSeverity => {
  const rank: Record<HandshakeSeverity, number> = { OK: 0, WARN: 1, INCOMPATIBLE: 2 };
  return rank[a] >= rank[b] ? a : b;
};

// -----------------------------------------------------------------------------
// Evaluator
// -----------------------------------------------------------------------------

export function evaluateHandshake(actual: RuntimeHandshake | null): HandshakeCompatibility {
  const evaluatedAt = new Date().toISOString();
  const expected = EXPECTED_HANDSHAKE;

  if (!actual) {
    return {
      severity: "INCOMPATIBLE",
      safeMode: true,
      reasons: [
        {
          code: "NO_HANDSHAKE",
          severity: "INCOMPATIBLE",
          message: "Runtime did not present a handshake. Safe mode engaged.",
        },
      ],
      expected,
      actual: null,
      evaluatedAt,
    };
  }

  const reasons: HandshakeReason[] = [];

  if (actual.protocolId !== expected.protocolId) {
    reasons.push({
      code: "PROTOCOL_ID_MISMATCH",
      severity: "INCOMPATIBLE",
      message: `Protocol id "${actual.protocolId}" does not match expected "${expected.protocolId}".`,
    });
  }

  const [expMaj, expMin] = parseSemver(expected.protocolVersion) ?? [0, 0, 0];
  const [actMaj, actMin] = parseSemver(actual.protocolVersion) ?? [-1, -1, -1];
  if (actMaj !== expMaj) {
    reasons.push({
      code: "PROTOCOL_MAJOR_MISMATCH",
      severity: "INCOMPATIBLE",
      message: `Protocol version ${actual.protocolVersion} incompatible with frontend ${expected.protocolVersion}.`,
    });
  } else if (actMin !== expMin) {
    reasons.push({
      code: "PROTOCOL_MINOR_DRIFT",
      severity: "WARN",
      message: `Protocol minor drift: runtime ${actual.protocolVersion} vs frontend ${expected.protocolVersion}.`,
    });
  }

  const [expSchMaj] = parseSemver(expected.schemaVersion) ?? [0];
  const [actSchMaj] = parseSemver(actual.schemaVersion) ?? [-1];
  if (actSchMaj !== expSchMaj) {
    reasons.push({
      code: "SCHEMA_MAJOR_MISMATCH",
      severity: "INCOMPATIBLE",
      message: `Snapshot schema ${actual.schemaVersion} incompatible with frontend schema ${expected.schemaVersion}.`,
    });
  } else if (actual.schemaVersion !== expected.schemaVersion) {
    reasons.push({
      code: "SCHEMA_MINOR_DRIFT",
      severity: "WARN",
      message: `Snapshot schema minor drift: runtime ${actual.schemaVersion} vs frontend ${expected.schemaVersion}.`,
    });
  }

  if (actual.schemaHash && actual.schemaHash !== expected.schemaHash) {
    reasons.push({
      code: "SCHEMA_HASH_DRIFT",
      severity: "INCOMPATIBLE",
      message: "Snapshot schema hash differs from the frontend-pinned canonical contract hash.",
    });
  }

  if (actual.runtimeVersion && cmpSemver(actual.runtimeVersion, expected.minRuntimeVersion) < 0) {
    reasons.push({
      code: "RUNTIME_TOO_OLD",
      severity: "INCOMPATIBLE",
      message: `Runtime ${actual.runtimeVersion} is older than minimum ${expected.minRuntimeVersion}.`,
    });
  }

  if (actual.minFrontendVersion && actual.frontendVersion) {
    if (cmpSemver(actual.frontendVersion, actual.minFrontendVersion) < 0) {
      reasons.push({
        code: "FRONTEND_TOO_OLD",
        severity: "INCOMPATIBLE",
        message: `Frontend ${actual.frontendVersion} is older than runtime-required minimum ${actual.minFrontendVersion}.`,
      });
    }
  }

  const actualFeatures = new Set(actual.supportedFeatures ?? []);
  for (const f of expected.requiredFeatures) {
    if (!actualFeatures.has(f)) {
      reasons.push({
        code: "MISSING_FEATURE",
        severity: "INCOMPATIBLE",
        message: `Runtime does not advertise required feature "${f}".`,
      });
    }
  }

  const actualCommands = new Set(actual.supportedCommands ?? []);
  const safetyCritical = new Set<RuntimeCommandKind>(expected.safetyCriticalCommands);
  for (const c of expected.requiredCommands) {
    if (!actualCommands.has(c)) {
      const isCritical = safetyCritical.has(c);
      reasons.push({
        code: isCritical ? "MISSING_CRITICAL_COMMAND" : "MISSING_COMMAND",
        severity: isCritical ? "INCOMPATIBLE" : "WARN",
        message: `Runtime does not advertise command "${c}"${isCritical ? " (safety critical)" : ""}.`,
      });
    }
  }

  const severity = reasons.reduce<HandshakeSeverity>(
    (acc, r) => worstSeverity(acc, r.severity),
    "OK",
  );

  return {
    severity,
    safeMode: severity === "INCOMPATIBLE",
    reasons,
    expected,
    actual,
    evaluatedAt,
  };
}

export function isInSafeMode(compat: HandshakeCompatibility | null | undefined): boolean {
  return !!compat && compat.safeMode;
}
