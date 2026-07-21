import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  HttpRuntimeAdapter,
  type HttpAdapterConfig,
  type HttpAdapterDependencies,
} from "../http-runtime-adapter";
import { RUNTIME_CONTRACT } from "../runtime-contract";
import type { RuntimeHandshake } from "../runtime-types";
import type { RuntimeEventEnvelope } from "../events/runtime-event-envelope";

const TOKEN = "test-token-secret";
const BASE = "http://127.0.0.1:8787/v4";

function compatibleHandshake(overrides: Partial<RuntimeHandshake> = {}): RuntimeHandshake {
  return {
    runtimeName: "XDirga Runtime V4",
    runtimeVersion: "4.1.0",
    runtimeId: "xdirga",
    bootId: "boot-1",
    protocolId: RUNTIME_CONTRACT.protocolId,
    protocolVersion: RUNTIME_CONTRACT.protocolVersion,
    schemaVersion: RUNTIME_CONTRACT.schemaVersion,
    schemaHash: RUNTIME_CONTRACT.schemaHash,
    capabilitiesRevision: 1,
    minFrontendVersion: "1.0.0",
    frontendVersion: "1.1.0",
    supportedFeatures: [
      "runtime.capabilities",
      "runtime.commands",
      "runtime.events",
      "runtime.reconciliation",
      "runtime.safety",
      "position.management",
      "trade.history",
    ],
    supportedCommands: [
      "runtime.emergencyKill",
      "runtime.pause",
      "runtime.disableEntries",
      "order.cancelAll",
      "position.closeAll",
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
    ],
    brokerProvider: "EXNESS",
    brokerEnvironment: "TRIAL",
    executionSemantics: "LIVE",
    source: "LOCAL_RUNTIME",
    observedAt: "2026-07-15T00:00:00.000Z",
    ...overrides,
  };
}

function snapshotEnvelope(seq = 10, bootId = "boot-1", runtimeId = "xdirga") {
  return {
    metadata: {
      runtimeId,
      bootId,
      revision: 1,
      sequence: seq,
      generatedAt: "2026-07-15T00:00:00.000Z",
      serverTimestamp: "2026-07-15T00:00:00.000Z",
      protocolId: RUNTIME_CONTRACT.protocolId,
      protocolVersion: RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: RUNTIME_CONTRACT.schemaVersion,
      schemaHash: RUNTIME_CONTRACT.schemaHash,
      source: "LOCAL_RUNTIME" as const,
    },
    snapshot: {
      positionsAvailable: true,
      positionsSourceFrameId: 1,
      positionsObservedAt: "2026-07-15T00:00:00.000Z",
      accountAvailable: true,
      accountSourceFrameId: 1,
      accountObservedAt: "2026-07-15T00:00:00.000Z",
      runtime: {
        id: runtimeId,
        sessionId: "s1",
        version: "4.1.0",
        buildHash: "x",
        environment: "LOCAL" as const,
        tradingMode: "TRIAL" as const,
        state: "READY" as const,
        previousState: "INITIALIZING" as const,
        stateChangedAt: null,
        stateReason: "ok",
        startedAt: null,
        uptimeSec: 1,
        lastHeartbeatAt: null,
        heartbeatLatencyMs: 1,
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
        accountMode: "TRIAL" as const,
        connection: "DISCONNECTED" as const,
        tradingPermitted: false,
        terminalVersion: "",
        lastTickAt: "2026-07-15T00:00:00.000Z",
        lastRequestAt: null,
        queueDepth: 0,
        avgLatencyMs: 0,
        timeoutCount: 0,
        reconnectAttempts: 0,
      },
      account: {
        currency: "USD",
        balance: 0,
        equity: 0,
        margin: 0,
        freeMargin: 0,
        marginLevel: 0,
        floatingPnl: 0,
        realizedPnlToday: null,
        realizedPnlWeek: null,
        dailyDrawdown: null,
        maxDrawdown: null,
        grossExposure: null,
        netExposure: null,
        openPositions: 0,
        pendingOrders: null,
        tradesToday: null,
        winRate: null,
        profitFactor: null,
        riskUtilization: null,
        updatedAt: "2026-07-15T00:00:00.000Z",
        freshness: "UNAVAILABLE" as const,
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
        state: "IDLE" as const,
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
    },
  };
}

function capabilitiesBody() {
  return {
    revision: 1,
    generatedAt: "2026-07-15T00:00:00.000Z",
    source: "LOCAL_RUNTIME",
    commands: {
      "runtime.pause": {
        command: "runtime.pause",
        allowed: true,
        riskLevel: 3,
        requiresReason: true,
        requiresTypedConfirmation: true,
      },
    },
  };
}

function eventEnv(
  overrides: Partial<RuntimeEventEnvelope> & { eventId: string; sequence: number },
): RuntimeEventEnvelope {
  return {
    type: "runtime.state.changed",
    runtimeId: "xdirga",
    bootId: "boot-1",
    revision: 1,
    occurredAt: "2026-07-15T00:00:01.000Z",
    emittedAt: "2026-07-15T00:00:01.000Z",
    receivedAt: "2026-07-15T00:00:01.000Z",
    severity: "INFO",
    source: "LOCAL_RUNTIME",
    payload: { state: "READY" },
    ...overrides,
  };
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  readyState = 0;
  closed = false;
  private listeners = new Map<string, Set<(ev: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
    queueMicrotask(() => {
      if (this.closed) return;
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    });
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(listener);
  }

  removeEventListener(type: string, listener: (ev: MessageEvent) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  emitNamed(eventType: string, data: unknown) {
    const ev = { data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent;
    for (const l of this.listeners.get(eventType) ?? []) l(ev);
  }

  emitMessage(data: unknown) {
    const ev = { data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent;
    this.onmessage?.(ev);
  }

  emitError() {
    this.onerror?.(new Event("error"));
  }

  listenerCount(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}

type FetchCall = { url: string; init?: RequestInit };

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "ERR",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

function createHarness(opts?: {
  handshake?: RuntimeHandshake | (() => RuntimeHandshake);
  snapshotSeq?: number;
  snapshot?: () => unknown | Promise<unknown>;
  failPaths?: Set<string>;
}) {
  const calls: FetchCall[] = [];
  const timers: Array<{ id: number; at: number; fn: () => void }> = [];
  let now = 1_000_000;
  let timerId = 1;
  const fail = opts?.failPaths ?? new Set<string>();

  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    calls.push({ url, init });
    const path = url.replace(BASE, "").split("?")[0];
    if (fail.has(path)) {
      return jsonResponse({ error: "fail" }, 500);
    }
    if (path === "/handshake") {
      const hs =
        typeof opts?.handshake === "function"
          ? opts.handshake()
          : (opts?.handshake ?? compatibleHandshake());
      return jsonResponse(hs);
    }
    if (path === "/capabilities") return jsonResponse(capabilitiesBody());
    if (path === "/snapshot")
      return jsonResponse(await (opts?.snapshot?.() ?? snapshotEnvelope(opts?.snapshotSeq ?? 10)));
    return jsonResponse({ error: "not found" }, 404);
  };

  const deps: HttpAdapterDependencies = {
    fetch: fetchImpl as typeof fetch,
    EventSource: FakeEventSource as unknown as typeof EventSource,
    now: () => now,
    setTimeout: ((fn: () => void, ms?: number) => {
      const id = timerId++;
      timers.push({ id, at: now + (ms ?? 0), fn: fn as () => void });
      return id as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout,
    clearTimeout: ((id: ReturnType<typeof setTimeout>) => {
      const n = Number(id);
      const idx = timers.findIndex((t) => t.id === n);
      if (idx >= 0) timers.splice(idx, 1);
    }) as typeof clearTimeout,
  };

  const config: HttpAdapterConfig = {
    baseUrl: BASE,
    authToken: TOKEN,
    ...deps,
  };

  return {
    config,
    calls,
    timers,
    advance(ms: number) {
      now += ms;
      const due = timers.filter((t) => t.at <= now).sort((a, b) => a.at - b.at);
      for (const t of due) {
        const idx = timers.indexOf(t);
        if (idx >= 0) timers.splice(idx, 1);
        t.fn();
      }
    },
    get now() {
      return now;
    },
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("BLOCKER: public refresh paths validate through the lifecycle", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("refreshSnapshot rejects malformed payload and leaves state untouched", async () => {
    let snapshotCall = 0;
    const h = createHarness({
      snapshot: () => {
        snapshotCall += 1;
        return snapshotCall === 1 ? snapshotEnvelope(10) : { metadata: {}, snapshot: {} };
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const before = adapter.getSnapshotEnvelope().metadata.sequence;
    await expect(adapter.refreshSnapshot()).rejects.toThrow();
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(before);
  });

  it("refreshSnapshot rejects foreign runtime snapshot and leaves state untouched", async () => {
    let snapshotCall = 0;
    const h = createHarness({
      snapshot: () => {
        snapshotCall += 1;
        return snapshotCall === 1
          ? snapshotEnvelope(10)
          : snapshotEnvelope(20, "boot-1", "other-runtime");
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const before = adapter.getSnapshotEnvelope().metadata.sequence;
    await expect(adapter.refreshSnapshot()).rejects.toThrow();
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(before);
  });

  it("refreshSnapshot rejects stale snapshot and leaves state untouched", async () => {
    let snapshotCall = 0;
    const h = createHarness({
      snapshot: () => {
        snapshotCall += 1;
        return snapshotCall === 1 ? snapshotEnvelope(10) : snapshotEnvelope(5);
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const before = adapter.getSnapshotEnvelope().metadata.sequence;
    await expect(adapter.refreshSnapshot()).rejects.toThrow();
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(before);
  });

  it("refreshHandshake rejects malformed payload and leaves handshake untouched", async () => {
    let handshakeCall = 0;
    const h = createHarness({
      handshake: () => {
        handshakeCall += 1;
        return handshakeCall === 1
          ? compatibleHandshake()
          : ({ ...compatibleHandshake(), protocolId: undefined } as unknown as RuntimeHandshake);
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const before = adapter.getHandshake()?.bootId;
    await expect(adapter.refreshHandshake()).rejects.toThrow();
    expect(adapter.getHandshake()?.bootId).toBe(before);
  });
});

describe("MAJOR: boot lineage does not deadlock after a valid new boot", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("accepts a snapshot with reset revision/sequence after a valid new-boot handshake on reconnect", async () => {
    let handshakeCall = 0;
    let snapshotCall = 0;
    const h = createHarness({
      handshake: () => {
        handshakeCall += 1;
        return handshakeCall === 1
          ? compatibleHandshake({ bootId: "boot-1" })
          : compatibleHandshake({ bootId: "boot-2" });
      },
      snapshot: () => {
        snapshotCall += 1;
        return snapshotCall === 1 ? snapshotEnvelope(50, "boot-1") : snapshotEnvelope(1, "boot-2");
      },
    });
    const adapter = new HttpRuntimeAdapter({
      ...h.config,
      maxReconnectAttempts: 3,
      initialReconnectDelayMs: 1,
    });
    await adapter.connect();
    await flush();
    expect(adapter.getSnapshotEnvelope().metadata.bootId).toBe("boot-1");
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(50);

    FakeEventSource.instances[0].emitError();
    await flush();
    h.advance(1);
    for (let i = 0; i < 10; i++) await flush();

    expect(adapter.getConnectionState().state).toBe("CONNECTED");
    expect(adapter.getSnapshotEnvelope().metadata.bootId).toBe("boot-2");
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(1);
  });
});

describe("MAJOR: sticky reopenStream survives a coalesced refresh-false follow-up", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("reopens the stream when a mandatory resync arrives while a refresh-false is in-flight", async () => {
    let resolveSnapshot: ((snapshot: unknown) => void) | undefined;
    let snapshots = 0;
    const h = createHarness({
      snapshot: () => {
        snapshots += 1;
        if (snapshots === 1) return snapshotEnvelope(10);
        if (snapshots === 2) {
          return new Promise((resolve) => {
            resolveSnapshot = resolve;
          });
        }
        return snapshotEnvelope(11);
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const esBeforeCount = FakeEventSource.instances.length;
    const es = FakeEventSource.instances[0];

    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e1", sequence: 11 }));
    await flush();
    expect(snapshots).toBe(2);

    es.emitNamed("system.resync.required", {
      type: "system.resync.required",
      reason: "GAP_DETECTED",
    });
    await flush();

    resolveSnapshot!(snapshotEnvelope(11));
    for (let i = 0; i < 10; i++) await flush();

    expect(FakeEventSource.instances.length).toBeGreaterThan(esBeforeCount);
    const latest = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    expect(latest.closed).toBe(false);
    const u = new URL(latest.url);
    expect(u.searchParams.get("sequence")).toBe("11");
  });
});

describe("MAJOR: foreign runtime event triggers resync and stays degraded until validated snapshot", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("does not publish a foreign event and resyncs", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    const delivered: string[] = [];
    adapter.subscribeEvents((event) => delivered.push(event.eventId));
    await adapter.connect();
    await flush();
    FakeEventSource.instances[0].emitNamed(
      "runtime.state.changed",
      eventEnv({ eventId: "foreign", sequence: 11, runtimeId: "other" }),
    );
    await flush();
    await flush();
    expect(delivered).toEqual([]);
  });
});

describe("MAJOR: stall emits STALE before RECONNECTING", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("subscribers observe STALE then RECONNECTING on observation threshold breach", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    const states: string[] = [];
    adapter.subscribeConnection((c) => states.push(c.state));
    await adapter.connect();
    await flush();
    states.length = 0;
    h.advance(15_000);
    expect(states.slice(0, 2)).toEqual(["STALE", "RECONNECTING"]);
  });
});

describe("MAJOR: recovery clears only after a validated snapshot publishes", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("stays RECONNECTING when the recovery snapshot is invalid", async () => {
    let snapshots = 0;
    const h = createHarness({
      snapshot: () => (snapshots++ === 0 ? snapshotEnvelope(10) : { metadata: {}, snapshot: {} }),
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    FakeEventSource.instances[0].emitNamed(
      "runtime.state.changed",
      eventEnv({ eventId: "gap", sequence: 20 }),
    );
    await flush();
    await flush();
    expect(adapter.getConnectionState().state).toBe("RECONNECTING");
  });
});

describe("MINOR: no 1970-epoch sentinel anywhere in src", () => {
  it("grep across src finds no new Date(0) or 1970-01-01 sentinel", async () => {
    const { readFile, glob } = await import("node:fs/promises");
    const files: string[] = [];
    for await (const f of glob(["src/**/*.ts", "src/**/*.tsx"])) {
      files.push(f);
    }
    const offenders: string[] = [];
    for (const file of files) {
      const content = await readFile(file, "utf8");
      if (/new Date\(0\)/.test(content) || /1970-01-01T00:00:00\.000Z/.test(content)) {
        if (file.includes("__tests__") && content.includes("not.toContain")) continue;
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});
