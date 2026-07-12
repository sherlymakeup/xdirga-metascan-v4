// Phase 5D — command equivalence + idempotency key derivation.
// Two commands are "equivalent" (and should dedupe against any active one) when
// they carry the same kind, target, and semantically identical parameters.

import type { RuntimeCommandKind } from "../runtime-types";

/** Parameters that meaningfully change the operation. Everything else is UX. */
const SIGNIFICANT_PARAMS: Partial<Record<RuntimeCommandKind, readonly string[]>> = {
  "position.modifyProtection": ["stopLoss", "takeProfit"],
  "position.closePartial": ["volume"],
  "order.cancel": [],
  "position.close": [],
};

function normalizedParams(
  kind: RuntimeCommandKind,
  parameters?: Record<string, unknown>,
): string {
  if (!parameters) return "";
  const keys = SIGNIFICANT_PARAMS[kind];
  const source = keys ? keys : Object.keys(parameters).sort();
  const flat: Record<string, unknown> = {};
  for (const k of source) {
    if (parameters[k] !== undefined) flat[k] = parameters[k];
  }
  return JSON.stringify(flat);
}

export function equivalenceKey(
  kind: RuntimeCommandKind,
  targetId?: string,
  parameters?: Record<string, unknown>,
): string {
  return `${kind}::${targetId ?? "-"}::${normalizedParams(kind, parameters)}`;
}

export function deriveIdempotencyKey(
  kind: RuntimeCommandKind,
  targetId?: string,
  parameters?: Record<string, unknown>,
): string {
  // Idempotency key IS the equivalence key. Active-command dedupe uses it directly.
  return equivalenceKey(kind, targetId, parameters);
}
