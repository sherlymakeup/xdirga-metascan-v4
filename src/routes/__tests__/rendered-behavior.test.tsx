import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { CockpitSnapshot } from "@/lib/types";
import type { RuntimeConnectionStateSnapshot } from "@/lib/runtime/runtime-types";

const mockSnapshotRef: { current: CockpitSnapshot } = {
  current: {} as CockpitSnapshot,
};
const mockConnectionRef: { current: RuntimeConnectionStateSnapshot } = {
  current: { state: "CONNECTED" } as RuntimeConnectionStateSnapshot,
};
const mockModeRef: { current: "fixture" | "http" } = { current: "http" };
const mockHasValidatedSnapshotRef: { current: boolean } = { current: false };
const mockNotificationsRef: { current: unknown[] } = { current: [] };

vi.mock("@/lib/runtime", () => ({
  getRuntimeMode: () => mockModeRef.current,
  useConnectionState: () => mockConnectionRef.current,
  useSnapshot: () => mockSnapshotRef.current,
  getRuntimeAdapter: () => ({
    sendCommand: vi.fn(),
  }),
  useCapability: () => ({
    allowed: true,
    riskLevel: 1,
    requiresReason: false,
    requiresTypedConfirmation: false,
  }),
  useHasValidatedSnapshot: () => mockHasValidatedSnapshotRef.current,
  useCommand: () => undefined,
  useCommandStore: () => [],
  useCommandCounts: () => ({ pending: 0, active: 0, completed: 0, failed: 0 }),
}));

vi.mock("@/lib/adapters/runtime", () => ({
  getRuntimeAdapter: () => ({
    sendCommand: vi.fn(),
    setScenario: vi.fn(),
  }),
  getRuntimeMode: () => mockModeRef.current,
  hydrateScenarioFromStorage: vi.fn(),
  useScenario: () => "healthy",
  useSnapshot: () => mockSnapshotRef.current,
}));

vi.mock("@/lib/runtime/events", () => ({
  useEventHistory: () => [],
  useEventHistoryPaused: () => false,
  eventHistoryStore: { subscribe: () => () => {}, list: () => [] },
}));

vi.mock("@/lib/runtime/events/notification-center", () => ({
  useActiveEventAlerts: () =>
    mockNotificationsRef.current.map((entry: any) => ({
      id: entry.latest.payload.id,
      severity: entry.latest.severity,
      title: entry.latest.payload.title,
      source: entry.latest.source,
      createdAt: entry.latest.occurredAt,
      description: entry.latest.type,
      suggestedAction: "Review alert details.",
      acknowledged: entry.acknowledged,
    })),
}));

import { PositionsPage } from "../positions";
import { EventsPage } from "../events";
import { CockpitPage } from "../index";
import type { Alert, Position } from "@/lib/types";

function emptySnapshot(): CockpitSnapshot {
  return {
    positionsAvailable: true,
    positionsSourceFrameId: null,
    positionsObservedAt: null,
    accountAvailable: true,
    accountSourceFrameId: null,
    accountObservedAt: null,
    runtime: {
      id: "rt",
      sessionId: "s1",
      version: "4.1.0",
      buildHash: "x",
      environment: "LOCAL",
      tradingMode: "TRIAL",
      state: "READY",
      previousState: "INITIALIZING",
      stateChangedAt: null,
      stateReason: "ok",
      startedAt: null,
      uptimeSec: null,
      lastHeartbeatAt: null,
      heartbeatLatencyMs: null,
      entriesEnabled: false,
      automationEnabled: false,
      hostname: null,
      os: null,
      pid: null,
    },
    subsystems: [],
    broker: {
      broker: "EXNESS",
      server: "",
      loginMasked: "***",
      accountMode: "TRIAL",
      connection: "DISCONNECTED",
      tradingPermitted: false,
      terminalVersion: "",
      lastTickAt: null,
      lastRequestAt: null,
      queueDepth: 0,
      avgLatencyMs: null,
      timeoutCount: 0,
      reconnectAttempts: 0,
    },
    account: {
      currency: "USD",
      balance: null,
      equity: null,
      margin: null,
      freeMargin: null,
      marginLevel: null,
      floatingPnl: null,
      realizedPnlToday: null,
      realizedPnlWeek: null,
      dailyDrawdown: null,
      maxDrawdown: null,
      grossExposure: null,
      netExposure: null,
      openPositions: null,
      pendingOrders: null,
      tradesToday: null,
      winRate: null,
      profitFactor: null,
      riskUtilization: null,
      updatedAt: null,
      freshness: "UNAVAILABLE",
    },
    strategies: [],
    positions: [],
    orders: [],
    markets: [],
    alerts: [],
    incidents: [],
    riskLimits: [],
    breakers: [],
    reconciliation: {
      state: "IDLE",
      lastRunAt: null,
      brokerOrders: 0,
      runtimeOrders: 0,
      brokerPositions: 0,
      runtimePositions: 0,
      missingOrders: 0,
      unknownOrders: 0,
      positionMismatches: 0,
      volumeMismatches: 0,
      stateMismatches: 0,
      issues: [],
    },
    events: [],
    equityCurve: [],
  } as unknown as CockpitSnapshot;
}

function stalePosition(): Position {
  return {
    id: "p1",
    brokerTicket: "T-001",
    ownership: "BOT_MANAGED",
    dataAvailable: false,
    sourceFrameId: 1,
    observedAt: null,
    symbol: "XAUUSD",
    side: "BUY",
    volume: 0.1,
    entryPrice: 2300,
    currentPrice: 2310,
    stopLoss: 2290,
    takeProfit: 2320,
    floatingPnl: 10,
    realizedPnl: 0,
    riskAmount: 10,
    riskPct: 0.5,
    openedAt: "2026-07-15T00:00:00.000Z",
    strategy: "scalper",
    protection: "PROTECTED",
    state: "OPEN",
    rMultiple: 1,
    mfe: null,
    mae: null,
    commission: 0,
    swap: 0,
    netPnl: 10,
    management: null,
  } as Position;
}

function unacknowledgedAlert(): Alert {
  return {
    id: "a1",
    severity: "HIGH",
    title: "Drawdown breach",
    source: "risk",
    createdAt: "2026-07-15T00:00:00.000Z",
    description: "Daily drawdown exceeded threshold.",
    suggestedAction: "Reduce position size.",
    acknowledged: false,
  } as Alert;
}

function managedPosition(): Position {
  return {
    ...stalePosition(),
    dataAvailable: true,
  } as Position;
}

function foreignPosition(): Position {
  return {
    ...stalePosition(),
    ownership: "FOREIGN",
    dataAvailable: true,
  } as Position;
}

function setSnapshot(snap: Partial<CockpitSnapshot>) {
  mockSnapshotRef.current = { ...emptySnapshot(), ...snap } as CockpitSnapshot;
}

function setConnection(conn: Partial<RuntimeConnectionStateSnapshot>) {
  mockConnectionRef.current = {
    ...mockConnectionRef.current,
    ...conn,
  } as RuntimeConnectionStateSnapshot;
}

describe("rendered-behavior: positions route", () => {
  beforeEach(() => {
    mockModeRef.current = "http";
    setSnapshot({});
    setConnection({ state: "CONNECTED" });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders retained stale rows when positionsAvailable=false but rows exist", () => {
    setSnapshot({
      positionsAvailable: false,
      positionsObservedAt: "2026-07-15T00:00:00.000Z",
      positions: [stalePosition()],
    });
    const html = renderToStaticMarkup(<PositionsPage />);
    expect(html).toContain("STALE");
    expect(html).toContain("Last observed");
    expect(html).toContain("Read-only");
    expect(html).not.toContain("Positions unavailable");
  });

  it("renders empty state only when positionsAvailable=false and no retained rows", () => {
    setSnapshot({
      positionsAvailable: false,
      positionsObservedAt: null,
      positions: [],
    });
    const html = renderToStaticMarkup(<PositionsPage />);
    expect(html).toContain("Positions unavailable");
    expect(html).not.toContain("STALE");
  });

  it("does not render Close all when there are zero positions", () => {
    mockModeRef.current = "fixture";
    setSnapshot({
      positionsAvailable: true,
      positionsObservedAt: "2026-07-15T00:00:00.000Z",
      positions: [],
    });
    const html = renderToStaticMarkup(<PositionsPage />);
    expect(html).not.toContain("Close all");
  });

  it("renders Close all when in demo mode and all positions are BOT_MANAGED", () => {
    mockModeRef.current = "fixture";
    setSnapshot({
      positionsAvailable: true,
      positionsObservedAt: "2026-07-15T00:00:00.000Z",
      positions: [managedPosition()],
    });
    const html = renderToStaticMarkup(<PositionsPage />);
    expect(html).toContain("Close all");
  });

  it("does not render Close all when a foreign position is present", () => {
    mockModeRef.current = "fixture";
    setSnapshot({
      positionsAvailable: true,
      positionsObservedAt: "2026-07-15T00:00:00.000Z",
      positions: [managedPosition(), foreignPosition()],
    });
    const html = renderToStaticMarkup(<PositionsPage />);
    expect(html).not.toContain("Close all");
  });
});

describe("rendered-behavior: events route", () => {
  beforeEach(() => {
    mockModeRef.current = "http";
    setSnapshot({ alerts: [unacknowledgedAlert()] });
    setConnection({ state: "CONNECTED" });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not show Acknowledged label for production unacknowledged alerts", () => {
    setSnapshot({ alerts: [unacknowledgedAlert()] });
    const html = renderToStaticMarkup(<EventsPage />);
    expect(html).not.toContain("✓ Acknowledged");
    expect(html).not.toContain("Acknowledge");
  });
});

describe("rendered-behavior: dashboard loading skeleton", () => {
  beforeEach(() => {
    mockModeRef.current = "http";
    mockHasValidatedSnapshotRef.current = false;
    setSnapshot({
      accountAvailable: true,
      account: {
        ...emptySnapshot().account,
        balance: 123456.78,
        tradesToday: 987,
        riskUtilization: 73,
        freshness: "FRESH",
      },
    });
    setConnection({ state: "CONNECTING" });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders skeleton placeholders and suppresses numeric telemetry while connecting", () => {
    setSnapshot({
      accountAvailable: true,
      account: {
        ...emptySnapshot().account,
        balance: 123456.78,
        tradesToday: 987,
        riskUtilization: 73,
        freshness: "FRESH",
      },
      strategies: [],
    });
    setConnection({ state: "CONNECTING" });
    mockHasValidatedSnapshotRef.current = false;
    const html = renderToStaticMarkup(<CockpitPage />);
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("123,456");
    expect(html).not.toContain("987");
    expect(html).not.toContain("73%");
  });

  it("renders skeleton when RECONNECTING without a validated snapshot", () => {
    setSnapshot({
      accountAvailable: true,
      account: {
        ...emptySnapshot().account,
        balance: 123456.78,
        tradesToday: 987,
        riskUtilization: 73,
        freshness: "FRESH",
      },
      strategies: [],
    });
    setConnection({ state: "RECONNECTING" });
    mockHasValidatedSnapshotRef.current = false;
    const html = renderToStaticMarkup(<CockpitPage />);
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("123,456");
    expect(html).not.toContain("987");
    expect(html).not.toContain("73%");
  });

  it("renders skeleton when ERROR without a validated snapshot", () => {
    setSnapshot({
      accountAvailable: true,
      account: {
        ...emptySnapshot().account,
        balance: 123456.78,
        tradesToday: 987,
        riskUtilization: 73,
        freshness: "FRESH",
      },
      strategies: [],
    });
    setConnection({ state: "ERROR" });
    mockHasValidatedSnapshotRef.current = false;
    const html = renderToStaticMarkup(<CockpitPage />);
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("123,456");
    expect(html).not.toContain("987");
    expect(html).not.toContain("73%");
  });

  it("renders an unresolved active alert received from the event notification store", () => {
    setSnapshot({ alerts: [] });
    setConnection({ state: "CONNECTED" });
    mockHasValidatedSnapshotRef.current = true;
    mockNotificationsRef.current = [
      {
        id: "alert.created|CRITICAL|-",
        acknowledged: false,
        firstSeenAt: "2026-07-23T00:00:00Z",
        lastSeenAt: "2026-07-23T00:00:00Z",
        count: 1,
        latest: {
          eventId: "event-alert-1",
          type: "alert.created",
          runtimeId: "runtime-1",
          bootId: "boot-1",
          revision: 1,
          sequence: 1,
          occurredAt: "2026-07-23T00:00:00Z",
          emittedAt: "2026-07-23T00:00:00Z",
          receivedAt: "2026-07-23T00:00:00Z",
          severity: "CRITICAL",
          source: "LOCAL_RUNTIME",
          payload: {
            id: "alien-4417215094",
            title: "Alien position detected",
            acknowledged: false,
          },
        },
        decision: { createAlert: true, priority: "CRITICAL" },
      },
    ];

    const html = renderToStaticMarkup(<CockpitPage />);

    expect(html).toContain("1 unresolved");
    expect(html).toContain("Alien position detected");
  });

  it("renders retained data (not skeleton) when validated snapshot exists and connection degrades", () => {
    setSnapshot({
      accountAvailable: true,
      account: {
        ...emptySnapshot().account,
        balance: 123456.78,
        tradesToday: 987,
        riskUtilization: 73,
        freshness: "FRESH",
      },
      strategies: [],
    });
    setConnection({ state: "RECONNECTING" });
    mockHasValidatedSnapshotRef.current = true;
    const html = renderToStaticMarkup(<CockpitPage />);
    expect(html).toContain("123,456");
    expect(html).toContain("987");
    expect(html).not.toContain("animate-pulse");
  });
});
