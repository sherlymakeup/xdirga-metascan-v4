// Centralized flag for gating every development-only control (scenario
// switcher, event simulator, handshake mismatch, fixture reset, diagnostics).
//
// Production builds MUST NOT expose controls that mutate fixture scenarios,
// synthesize events, or reset frontend-only state. Callers that need to
// conditionally render such UI import ONLY from this module.

export const DEVELOPMENT_FEATURES_ENABLED: boolean =
  typeof import.meta !== "undefined" && import.meta.env ? import.meta.env.DEV === true : false;

/** Convenience predicate for readable call sites. */
export function areDevelopmentFeaturesEnabled(): boolean {
  return DEVELOPMENT_FEATURES_ENABLED;
}
