import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const modeRef: { current: "fixture" | "http" } = { current: "http" };
const notificationsRef: { current: unknown[] } = { current: [] };

vi.mock("@/lib/runtime", () => ({
  getRuntimeMode: () => modeRef.current,
}));

vi.mock("@/lib/adapters/runtime", () => ({
  getRuntimeAdapter: () => ({ setScenario: vi.fn() }),
  getRuntimeMode: () => modeRef.current,
  hydrateScenarioFromStorage: vi.fn(),
  useScenario: () => "healthy",
  useSnapshot: () => ({
    runtime: {
      state: "READY",
      stateReason: "ok",
      stateChangedAt: null,
      lastHeartbeatAt: null,
      uptimeSec: null,
      entriesEnabled: false,
    },
    broker: { avgLatencyMs: null },
    account: { freshness: "UNAVAILABLE" },
  }),
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
import { TopStatusBar } from "@/components/cockpit/top-status-bar";

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
});
