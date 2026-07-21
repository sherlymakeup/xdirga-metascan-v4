import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  HttpRuntimeAdapter,
  type HttpAdapterConfig,
  type HttpAdapterDependencies,
} from "../http-runtime-adapter";
import { RUNTIME_CONTRACT } from "../runtime-contract";
import type { RuntimeHandshake } from "../runtime-types";
import type { RuntimeEventEnvelope } from "../events/runtime-event-envelope";
import { validateHandshake, validateSnapshot } from "../events/event-schemas";

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

function snapshotEnvelope(seq = 10, bootId = "boot-1") {
  return {
    metadata: {
      runtimeId: "xdirga",
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
        id: "xdirga",
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

  /** Backend-shaped named SSE frame (`event: <type>`). Does not fire onmessage. */
  emitNamed(eventType: string, data: unknown) {
    const ev = { data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent;
    for (const l of this.listeners.get(eventType) ?? []) l(ev);
  }

  /** Untyped/default message frame only. */
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
  commandPost?: (body: unknown) => unknown;
  commandGet?: (id: string) => unknown;
  history?: (url: string) => unknown;
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
    if (path === "/commands" && (init?.method ?? "GET").toUpperCase() === "POST") {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      const res =
        opts?.commandPost?.(body) ??
        ({
          commandId: "cmd-1",
          state: "PREPARED",
          receivedAt: "2026-07-15T00:00:02.000Z",
          idempotencyKey: body.idempotencyKey,
        } as const);
      return jsonResponse(res, 200);
    }
    if (path.startsWith("/commands/")) {
      const id = path.slice("/commands/".length);
      const res =
        opts?.commandGet?.(id) ??
        ({
          commandId: id,
          clientRequestId: "cr-1",
          correlationId: "corr-1",
          idempotencyKey: "idem-1",
          kind: "runtime.pause",
          state: "IN_PROGRESS",
          createdAt: "2026-07-15T00:00:02.000Z",
          updatedAt: "2026-07-15T00:00:03.000Z",
        } as const);
      return jsonResponse(res);
    }
    if (path === "/history/trades") {
      const res = opts?.history?.(url) ?? { trades: [], nextCursor: null };
      return jsonResponse(res);
    }
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

describe("runtime wire validation", () => {
  it("rejects malformed nested account, positions, markets, and enums", () => {
    const account = snapshotEnvelope();
    (account.snapshot.account as { balance: unknown }).balance = "invalid";
    expect(validateSnapshot(account).ok).toBe(false);
    const position = snapshotEnvelope();
    (position.snapshot as { positions: unknown[] }).positions = [{ id: "p1" }];
    expect(validateSnapshot(position).ok).toBe(false);
    const market = snapshotEnvelope();
    (market.snapshot as { markets: unknown[] }).markets = [
      { symbol: "XAUUSD", freshness: "INVALID" },
    ];
    expect(validateSnapshot(market).ok).toBe(false);
  });

  it("rejects incomplete handshake broker semantics", () => {
    expect(validateHandshake({ ...compatibleHandshake(), brokerEnvironment: "PAPER" }).ok).toBe(
      false,
    );
    expect(validateHandshake({ ...compatibleHandshake(), brokerProvider: undefined }).ok).toBe(
      false,
    );
  });
});

describe("HttpRuntimeAdapter", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => {
    FakeEventSource.instances = [];
  });

  it("I: REST Bearer auth; SSE encoded query token only", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();

    const rest = h.calls.filter((c) => !c.url.includes("/events/stream"));
    expect(rest.length).toBeGreaterThan(0);
    for (const c of rest) {
      const headers = new Headers(c.init?.headers);
      expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
      expect(c.url).not.toContain("token=");
    }

    expect(FakeEventSource.instances).toHaveLength(1);
    const sseUrl = FakeEventSource.instances[0].url;
    expect(sseUrl).toContain(`token=${encodeURIComponent(TOKEN)}`);
    expect(sseUrl).toContain("bootId=");
    expect(sseUrl).not.toMatch(/Authorization/i);
  });

  it("I: URL join is deterministic and encodes special token chars", async () => {
    const special = "a b/c?d=e&f=g";
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter({
      ...h.config,
      baseUrl: "http://127.0.0.1:8787/v4/",
      authToken: special,
    });
    await adapter.connect();
    await flush();
    const sseUrl = FakeEventSource.instances[0].url;
    expect(sseUrl.startsWith("http://127.0.0.1:8787/v4/events/stream?")).toBe(true);
    expect(sseUrl).not.toContain("//events");
    const tokenParam = new URL(sseUrl).searchParams.get("token");
    expect(tokenParam).toBe(special);
    for (const c of h.calls) {
      expect(c.url).not.toContain(special);
    }
  });

  it("J: handshake success connects; major mismatch fail-closed", async () => {
    const ok = createHarness();
    const a1 = new HttpRuntimeAdapter(ok.config);
    await a1.connect();
    await flush();
    expect(a1.getConnectionState().state).toBe("CONNECTED");
    expect(a1.getHandshake()?.bootId).toBe("boot-1");
    await a1.disconnect();

    FakeEventSource.instances = [];
    const bad = createHarness({
      handshake: compatibleHandshake({ protocolVersion: "5.0.0", schemaVersion: "2.0.0" }),
    });
    const a2 = new HttpRuntimeAdapter(bad.config);
    await expect(a2.connect()).rejects.toThrow();
    expect(a2.getConnectionState().state).toBe("ERROR");
    expect(a2.getConnectionState().state).not.toBe("CONNECTED");
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("J: schema hash mismatch fail-closed", async () => {
    const h = createHarness({
      handshake: compatibleHandshake({ schemaHash: "deadbeef" }),
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await expect(adapter.connect()).rejects.toThrow();
    expect(adapter.getConnectionState().state).toBe("ERROR");
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("K: hydrates capabilities+snapshot then one EventSource; listeners exact", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    const snaps: string[] = [];
    const hands: string[] = [];
    const conns: string[] = [];
    adapter.subscribeSnapshot((e) => snaps.push(e.metadata.bootId));
    adapter.subscribeHandshake((x) => hands.push(x?.bootId ?? "null"));
    adapter.subscribeConnection((c) => conns.push(c.state));

    await adapter.connect();
    await flush();

    const paths = h.calls.map((c) => c.url.replace(BASE, "").split("?")[0]);
    expect(paths.slice(0, 3)).toEqual(["/handshake", "/capabilities", "/snapshot"]);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(adapter.getCapabilities().commands["runtime.pause"]?.allowed).toBe(true);
    expect(adapter.getSnapshot().runtime.id).toBe("xdirga");
    expect(snaps).toContain("boot-1");
    expect(hands).toContain("boot-1");
    expect(conns).toContain("CONNECTED");

    const unsub = adapter.subscribeSnapshot(() => snaps.push("x"));
    unsub();
    await adapter.refreshSnapshot();
    expect(snaps.filter((s) => s === "x")).toHaveLength(0);
  });

  it("L: named SSE event types deliver; drops duplicates; onmessage alone insufficient", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    const events: string[] = [];
    adapter.subscribeEvents((e) => events.push(e.eventId));
    await adapter.connect();
    await flush();
    const es = FakeEventSource.instances[0];
    expect(es.listenerCount("runtime.state.changed")).toBeGreaterThan(0);
    expect(es.listenerCount("system.resync.required")).toBeGreaterThan(0);
    const e1 = eventEnv({ eventId: "e1", sequence: 11 });
    es.emitNamed("runtime.state.changed", e1);
    es.emitNamed("runtime.state.changed", e1);
    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e2", sequence: 12 }));
    es.emitMessage(eventEnv({ eventId: "e-untyped", sequence: 13 }));
    expect(events).toEqual(["e1", "e2"]);
  });

  it("M: sequence gap and bootId change discard the event then resync", async () => {
    const h = createHarness({ snapshotSeq: 10 });
    const adapter = new HttpRuntimeAdapter(h.config);
    const delivered: string[] = [];
    adapter.subscribeEvents((e) => delivered.push(e.eventId));
    await adapter.connect();
    await flush();
    const before = h.calls.filter((c) => c.url.includes("/snapshot")).length;
    FakeEventSource.instances[0].emitNamed(
      "runtime.state.changed",
      eventEnv({ eventId: "e-gap", sequence: 20 }),
    );
    await flush();
    await flush();
    expect(h.calls.filter((c) => c.url.includes("/snapshot")).length).toBeGreaterThan(before);
    expect(delivered).not.toContain("e-gap");

    const beforeBoot = h.calls.filter((c) => c.url.includes("/snapshot")).length;
    delivered.length = 0;
    const current = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    current.emitNamed(
      "runtime.state.changed",
      eventEnv({ eventId: "e-boot", sequence: 1, bootId: "boot-2" }),
    );
    await flush();
    await flush();
    expect(h.calls.filter((c) => c.url.includes("/snapshot")).length).toBeGreaterThan(beforeBoot);
    expect(delivered).not.toContain("e-boot");
  });

  it("M: system.resync.required control frame triggers snapshot resync", async () => {
    const h = createHarness({ snapshotSeq: 10 });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const before = h.calls.filter((c) => c.url.includes("/snapshot")).length;
    const es = FakeEventSource.instances[0];
    es.emitNamed("system.resync.required", {
      type: "system.resync.required",
      reason: "GAP_DETECTED",
    });
    await flush();
    await flush();
    expect(h.calls.filter((c) => c.url.includes("/snapshot")).length).toBeGreaterThan(before);
  });

  it("N: disconnect closes EventSource, clears timers; reconnect bounded; one active ES", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    expect(FakeEventSource.instances).toHaveLength(1);
    FakeEventSource.instances[0].emitError();
    await flush();
    expect(adapter.getConnectionState().state).toBe("RECONNECTING");
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(h.timers.length).toBeGreaterThan(0);
    h.advance(500);
    await flush();
    await flush();
    const openAfter = FakeEventSource.instances.filter((i) => !i.closed);
    expect(openAfter.length).toBeLessThanOrEqual(1);
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(1);

    await adapter.disconnect();
    expect(FakeEventSource.instances.every((i) => i.closed)).toBe(true);
    expect(h.timers).toHaveLength(0);
    expect(adapter.getConnectionState().state).toBe("DISCONNECTED");
  });

  it("N: marks connected data stale after the client observation threshold", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    expect(adapter.getConnectionState().state).toBe("CONNECTED");
    h.advance(15_000);
    expect(adapter.getConnectionState().state).toBe("RECONNECTING");
    expect(adapter.getConnectionState().dataAgeMs).toBe(15_000);
  });

  it("O: network error rejects honestly; no fixture fallback", async () => {
    const h = createHarness({ failPaths: new Set(["/handshake"]) });
    const adapter = new HttpRuntimeAdapter(h.config);
    await expect(adapter.connect()).rejects.toThrow();
    expect(adapter.isDevelopmentFixture()).toBe(false);
    expect(adapter.isDemo()).toBe(false);
    expect(adapter.getDescriptor().dataSource).toBe("LOCAL_RUNTIME");
    expect(adapter.getSnapshot().runtime.id).toBe("rt_disconnected");
  });

  it("O: malformed SSE payload does not throw; getters safe", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const es = FakeEventSource.instances[0];
    expect(() => es.emitMessage({ not: "an envelope" })).not.toThrow();
    expect(() => adapter.getSnapshot()).not.toThrow();
    expect(() => adapter.getCapabilities()).not.toThrow();
    expect(() => adapter.getConnectionState()).not.toThrow();
    expect(() => adapter.getOperator()).not.toThrow();
  });

  it("P: production commands reject without an HTTP request", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    await expect(
      adapter.submitCommand({
        clientRequestId: "cr-1",
        idempotencyKey: "idem-1",
        correlationId: "corr-1",
        kind: "runtime.pause",
        submittedAt: "2026-07-15T00:00:02.000Z",
      }),
    ).rejects.toThrow("Commands are available only in the development fixture.");
    expect(h.calls.some((call) => call.url.endsWith("/commands"))).toBe(false);
  });

  it("Q: trade history preserves opaque cursor and query encoding", async () => {
    const h = createHarness({
      history: (url) => {
        const u = new URL(url);
        return {
          trades: [],
          nextCursor: u.searchParams.get("cursor") === "opaque/cursor+1" ? null : "next",
        };
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    const page = await adapter.getTradeHistory({ cursor: "opaque/cursor+1", limit: 25 });
    const hist = h.calls.find((c) => c.url.includes("/history/trades"));
    expect(hist).toBeTruthy();
    const u = new URL(hist!.url);
    expect(u.searchParams.get("cursor")).toBe("opaque/cursor+1");
    expect(u.searchParams.get("limit")).toBe("25");
    expect(page.nextCursor).toBeNull();
  });

  it("R: read getters never throw; async write failures honest", async () => {
    const adapter = new HttpRuntimeAdapter({
      baseUrl: BASE,
      authToken: TOKEN,
      fetch: async () => {
        throw new Error("network down");
      },
      EventSource: FakeEventSource as unknown as typeof EventSource,
    });
    expect(() => adapter.getSnapshot()).not.toThrow();
    expect(() => adapter.getSnapshotEnvelope()).not.toThrow();
    expect(() => adapter.getCapabilities()).not.toThrow();
    expect(() => adapter.getHandshake()).not.toThrow();
    expect(() => adapter.getConnectionState()).not.toThrow();
    expect(() => adapter.getOperator()).not.toThrow();
    expect(() => adapter.getDescriptor()).not.toThrow();
    await expect(adapter.connect()).rejects.toThrow();
    await expect(
      adapter.submitCommand({
        clientRequestId: "x",
        idempotencyKey: "y",
        correlationId: "z",
        kind: "runtime.pause",
        submittedAt: "2026-07-15T00:00:00.000Z",
      }),
    ).rejects.toThrow();
  });

  it("S: production selection uses HTTP config; never fixture", () => {
    const adapter = new HttpRuntimeAdapter({ baseUrl: BASE, authToken: TOKEN });
    expect(adapter.adapterType).toBe("http");
    expect(adapter.isDevelopmentFixture()).toBe(false);
    expect(adapter.isDemo()).toBe(false);
    expect(adapter.getDescriptor()).toEqual({
      adapterType: "HTTP_LOCAL_RUNTIME",
      dataSource: "LOCAL_RUNTIME",
      isDevelopmentOnly: false,
    });
  });

  it("CONNECTED only after EventSource onopen, not after REST hydrate alone", async () => {
    const h = createHarness();
    class ManualES {
      static instances: ManualES[] = [];
      url: string;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      onopen: ((ev: Event) => void) | null = null;
      readyState = 0;
      closed = false;
      private listeners = new Map<string, Set<(ev: MessageEvent) => void>>();
      constructor(url: string) {
        this.url = url;
        ManualES.instances.push(this);
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
      open() {
        this.readyState = 1;
        this.onopen?.(new Event("open"));
      }
    }
    ManualES.instances = [];
    const adapter = new HttpRuntimeAdapter({
      ...h.config,
      EventSource: ManualES as unknown as typeof EventSource,
    });
    const p = adapter.connect();
    for (let i = 0; i < 20 && ManualES.instances.length === 0; i += 1) {
      await flush();
    }
    expect(adapter.getConnectionState().state).toBe("CONNECTING");
    expect(ManualES.instances.length).toBe(1);
    ManualES.instances[0].open();
    await p;
    await flush();
    expect(adapter.getConnectionState().state).toBe("CONNECTED");
  });

  it("reconnect SSE URL resumes via sequence query (not Last-Event-ID header)", async () => {
    const h = createHarness({ snapshotSeq: 10 });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const firstUrl = FakeEventSource.instances[0].url;
    expect(new URL(firstUrl).searchParams.get("sequence")).toBe("10");
    expect(new URL(firstUrl).searchParams.get("bootId")).toBe("boot-1");
    FakeEventSource.instances[0].emitError();
    await flush();
    h.advance(500);
    await flush();
    await flush();
    const last = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    const u = new URL(last.url);
    expect(u.searchParams.has("sequence")).toBe(true);
    expect(u.searchParams.has("bootId")).toBe(true);
    expect(u.searchParams.get("token")).toBe(TOKEN);
  });

  it("disconnect removes SSE named listeners and closes stream", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const es = FakeEventSource.instances[0];
    expect(es.listenerCount("runtime.state.changed")).toBeGreaterThan(0);
    await adapter.disconnect();
    expect(es.closed).toBe(true);
    expect(es.listenerCount("runtime.state.changed")).toBe(0);
    expect(es.listenerCount("system.resync.required")).toBe(0);
  });

  it("errors never include raw auth token", async () => {
    const h = createHarness({ failPaths: new Set(["/handshake"]) });
    const adapter = new HttpRuntimeAdapter({
      ...h.config,
      authToken: "super-secret-token-xyz",
    });
    try {
      await adapter.connect();
      expect.fail("should reject");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      expect(msg).not.toContain("super-secret-token-xyz");
    }
    const errMsg = adapter.getConnectionState().errorMessage ?? "";
    expect(errMsg).not.toContain("super-secret-token-xyz");
  });

  it("refreshes one authoritative snapshot for coalesced valid events", async () => {
    const h = createHarness({ snapshotSeq: 10 });
    const adapter = new HttpRuntimeAdapter(h.config);
    const delivered: string[] = [];
    adapter.subscribeEvents((event) => delivered.push(event.eventId));
    await adapter.connect();
    await flush();
    const before = h.calls.filter((call) => call.url.includes("/snapshot")).length;
    const es = FakeEventSource.instances[0];
    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e1", sequence: 11 }));
    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e2", sequence: 12 }));
    await flush();
    await flush();
    expect(h.calls.filter((call) => call.url.includes("/snapshot")).length).toBe(before + 1);
    expect(delivered).toEqual(["e1", "e2"]);
  });

  it("discards a gap event, resyncs, and reopens from the snapshot cursor", async () => {
    const h = createHarness({ snapshotSeq: 10 });
    const adapter = new HttpRuntimeAdapter(h.config);
    const delivered: string[] = [];
    adapter.subscribeEvents((event) => delivered.push(event.eventId));
    await adapter.connect();
    await flush();
    FakeEventSource.instances[0].emitNamed(
      "runtime.state.changed",
      eventEnv({ eventId: "gap", sequence: 20 }),
    );
    await flush();
    await flush();
    expect(delivered).toEqual([]);
    const latest = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    expect(new URL(latest.url).searchParams.get("sequence")).toBe("10");
  });

  it("follows up once when an event arrives during an in-flight snapshot refresh", async () => {
    let resolveSnapshot: ((snapshot: unknown) => void) | undefined;
    let snapshots = 0;
    const h = createHarness({
      snapshot: () => {
        snapshots += 1;
        if (snapshots === 1) return snapshotEnvelope(10);
        return new Promise((resolve) => {
          resolveSnapshot = resolve;
        });
      },
    });
    const adapter = new HttpRuntimeAdapter(h.config);
    await adapter.connect();
    await flush();
    const es = FakeEventSource.instances[0];
    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e1", sequence: 11 }));
    await flush();
    es.emitNamed("runtime.state.changed", eventEnv({ eventId: "e2", sequence: 12 }));
    await flush();
    expect(snapshots).toBe(2);
    resolveSnapshot!(snapshotEnvelope(11));
    await flush();
    await flush();
    expect(snapshots).toBe(3);
  });

  it("rejects an older snapshot after a gap", async () => {
    let snapshots = 0;
    const h = createHarness({
      snapshot: () => (snapshots++ === 0 ? snapshotEnvelope(10) : snapshotEnvelope(9)),
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
    expect(adapter.getSnapshotEnvelope().metadata.sequence).toBe(10);
  });

  it("foreign runtime event resyncs without publishing", async () => {
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
    expect(delivered).toEqual([]);
  });

  it("clears recovery only after a valid snapshot publishes", async () => {
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

  it("stale reconnects then errors after exhaustion", async () => {
    const h = createHarness();
    const adapter = new HttpRuntimeAdapter({
      ...h.config,
      maxReconnectAttempts: 1,
      initialReconnectDelayMs: 1,
    });
    await adapter.connect();
    await flush();
    h.advance(15_000);
    expect(adapter.getConnectionState().state).toBe("RECONNECTING");
    h.advance(1);
    await flush();
    FakeEventSource.instances[FakeEventSource.instances.length - 1].emitError();
    await flush();
    expect(adapter.getConnectionState().state).toBe("ERROR");
  });
});
