import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const modeRef: { current: "fixture" | "http" } = { current: "http" };
const notificationsRef: { current: unknown[] } = { current: [] };
const runtimeRef = {
  current: {
    state: "READY",
    stateReason: "ok",
    stateChangedAt: null as string | null,
    lastHeartbeatAt: null,
    uptimeSec: null,
    entriesEnabled: false,
  },
};
const operationalRef = {
  current: {
    state: "NORMAL",
    reasons: [] as string[],
    recommendedActions: [] as string[],
  },
};
const eventsRef: { current: unknown[] } = { current: [] };

vi.mock("@/lib/runtime", () => ({
  getRuntimeMode: () => modeRef.current,
}));

vi.mock("@/lib/adapters/runtime", () => ({
  getRuntimeAdapter: () => ({ setScenario: vi.fn() }),
  getRuntimeMode: () => modeRef.current,
  hydrateScenarioFromStorage: vi.fn(),
  useScenario: () => "healthy",
  useSnapshot: () => ({
    runtime: runtimeRef.current,
    broker: { avgLatencyMs: null },
    account: { freshness: "UNAVAILABLE" },
  }),
}));

vi.mock("@/lib/runtime/state/operational-state", () => ({
  useGlobalOperationalState: () => operationalRef.current,
}));

vi.mock("@/lib/runtime/events/event-store", () => ({
  useEventHistory: () => eventsRef.current,
}));

vi.mock("@/lib/runtime/events/notification-center", () => ({
  notificationCenter: {
    acknowledgeAll: vi.fn(),
    clear: vi.fn(),
    acknowledge: vi.fn(),
  },
  useNotifications: () => notificationsRef.current,
  useNotificationCounts: () => ({
    critical: 1,
    warning: 0,
    unread: 0,
    acknowledged: 2,
    fixture: 0,
    total: 2,
  }),
}));

vi.mock("@/components/commands/CommandCenter", () => ({
  CommandCenterButton: () => null,
}));
vi.mock("@/components/runtime/environment-badges", () => ({
  BrokerConnectionBadge: () => null,
  BrokerEnvironmentBadge: () => null,
  BrokerTargetBadge: () => null,
  DataSourceBadge: () => null,
  ExecutionSemanticsBadge: () => null,
  LocalRuntimeConnectionBadge: () => null,
}));

import { NotificationCenterDrawer } from "@/components/runtime/NotificationCenter";
import { GlobalOperationalStateBanner } from "@/components/runtime/GlobalOperationalStateBanner";
import { TopStatusBar } from "@/components/cockpit/top-status-bar";
import { runtimeTone } from "@/components/cockpit/runtime-state-badge";

function notification(id: string, type: string) {
  return {
    id,
    acknowledged: true,
    firstSeenAt: "2026-07-23T00:00:00Z",
    lastSeenAt: "2026-07-23T00:00:00Z",
    count: 1,
    latest: {
      eventId: id,
      type,
      runtimeId: "runtime-1",
      bootId: "boot-1",
      revision: 1,
      sequence: 1,
      occurredAt: "2026-07-23T00:00:00Z",
      emittedAt: "2026-07-23T00:00:00Z",
      receivedAt: "2026-07-23T00:00:00Z",
      severity: "CRITICAL",
      source: "LOCAL_RUNTIME",
      payload: {},
    },
    decision: { priority: "CRITICAL" },
  };
}

describe("live cockpit overlays", () => {
  it("renders all stored notifications in the drawer body by default", () => {
    notificationsRef.current = [
      notification("notification-1", "alert.created"),
      notification("notification-2", "runtime.state.changed"),
    ];

    const html = renderToStaticMarkup(<NotificationCenterDrawer onClose={() => {}} />);

    expect(html).toContain("alert.created");
    expect(html).toContain("runtime.state.changed");
  });

  it("hides fixture controls for the LOCAL_RUNTIME http source", () => {
    modeRef.current = "http";
    const html = renderToStaticMarkup(<TopStatusBar />);
    expect(html).not.toContain("Development fixture scenario");
  });

  it("keeps fixture controls for the development fixture source", () => {
    modeRef.current = "fixture";
    const html = renderToStaticMarkup(<TopStatusBar />);
    expect(html).toContain("Development fixture scenario");
  });

  it("renders exactly one degraded banner with reasons and since text", () => {
    runtimeRef.current = {
      ...runtimeRef.current,
      state: "DEGRADED",
      stateReason: "MT5_DEGRADED",
      stateChangedAt: null,
    };
    operationalRef.current = {
      state: "DEGRADED",
      reasons: ["Runtime is DEGRADED."],
      recommendedActions: [],
    };
    eventsRef.current = [
      {
        type: "runtime.health.changed",
        receivedAt: "2026-07-23T00:00:00Z",
        payload: { state: "DEGRADED", reasons: ["TICK_AGE"] },
      },
    ];

    const html = renderToStaticMarkup(
      <>
        <TopStatusBar />
        <GlobalOperationalStateBanner />
      </>,
    );

    expect(html.match(/data-operational-banner=/g)).toHaveLength(1);
    expect(html).toContain("DEGRADED");
    expect(html).toContain("MT5_DEGRADED");
    expect(html).toContain("TICK_AGE");
    expect(html).toContain("sejak");
  });

  it("keeps the reserved strip empty when connected", () => {
    runtimeRef.current = {
      ...runtimeRef.current,
      state: "READY",
      stateReason: "ok",
      stateChangedAt: null,
    };
    operationalRef.current = { state: "NORMAL", reasons: [], recommendedActions: [] };

    const html = renderToStaticMarkup(
      <>
        <TopStatusBar />
        <GlobalOperationalStateBanner />
      </>,
    );

    expect(html.match(/data-status-strip=/g)).toHaveLength(1);
    expect(html).not.toContain("data-operational-banner");
  });

  it("maps degraded to amber, safe states to red, and connected to green", () => {
    expect(runtimeTone("DEGRADED")).toBe("warn");
    expect(runtimeTone("KILLED")).toBe("crit");
    expect(runtimeTone("READY")).toBe("ok");
  });

  it("renders global degraded banner while runtime is ready", () => {
    runtimeRef.current = { ...runtimeRef.current, state: "READY" };
    operationalRef.current = {
      state: "DEGRADED",
      reasons: ["Broker data is delayed."],
      recommendedActions: [],
    };

    const html = renderToStaticMarkup(<GlobalOperationalStateBanner />);

    expect(html).toContain("Operational state: DEGRADED");
  });

  it("mutes global degraded banner while runtime strip is speaking", () => {
    runtimeRef.current = { ...runtimeRef.current, state: "DEGRADED" };
    operationalRef.current = {
      state: "DEGRADED",
      reasons: ["Runtime is degraded."],
      recommendedActions: [],
    };

    expect(renderToStaticMarkup(<GlobalOperationalStateBanner />)).toBe("");
  });

  it("keeps global banner hidden for normal operation", () => {
    runtimeRef.current = { ...runtimeRef.current, state: "READY" };
    operationalRef.current = { state: "NORMAL", reasons: [], recommendedActions: [] };

    expect(renderToStaticMarkup(<GlobalOperationalStateBanner />)).toBe("");
  });

  it.each(["RESTRICTED", "BLOCKED", "DISCONNECTED", "SAFE_MODE"] as const)(
    "keeps global %s banner visible",
    (state) => {
      runtimeRef.current = { ...runtimeRef.current, state: "READY" };
      operationalRef.current = { state, reasons: [state], recommendedActions: [] };

      expect(renderToStaticMarkup(<GlobalOperationalStateBanner />)).toContain(
        `Operational state: ${state.replace("_", " ")}`,
      );
    },
  );
});
