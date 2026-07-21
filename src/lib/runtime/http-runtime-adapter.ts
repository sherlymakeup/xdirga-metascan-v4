// HTTP + SSE adapter for LOCAL_RUNTIME.
// Transport: REST + Server-Sent Events (no WebSockets).
// Auth: REST Bearer header; SSE `?token=` query (EventSource cannot set headers).

import type { RuntimeAdapter } from "./runtime-adapter";
import { RUNTIME_CONTRACT } from "./runtime-contract";
import { buildCapabilities } from "./runtime-capabilities";
import { createEmptySnapshot } from "@/lib/demo/scenarios";
import { evaluateHandshake } from "./runtime-handshake";
import { EventDeduplicator } from "./events/event-deduplicator";
import { validateEnvelope } from "./events/event-schemas";
import { validateTransition } from "./commands/command-transitions";
import { RUNTIME_EVENT_TYPES } from "./events/runtime-event-envelope";
import type {
  CommandAccepted,
  OperatorIdentity,
  RuntimeAdapterDescriptor,
  RuntimeCapabilities,
  RuntimeCommandRequest,
  RuntimeCommandStatus,
  RuntimeConnectionStateSnapshot,
  RuntimeEventEnvelope,
  RuntimeHandshake,
  RuntimeSnapshotEnvelope,
} from "./runtime-types";
import type { CockpitSnapshot, TradeHistoryPage, TradeHistoryQuery } from "@/lib/types";

const SSE_NAMED_TYPES = [...RUNTIME_EVENT_TYPES, "system.resync.required"] as const;
// Client-observation threshold only; this is not a claim about server heartbeat delivery.
export const CLIENT_OBSERVATION_STALE_AFTER_MS = 15_000;

export interface HttpAdapterDependencies {
  fetch?: typeof fetch;
  EventSource?: typeof EventSource;
  now?: () => number;
  setTimeout?: typeof setTimeout;
  clearTimeout?: typeof clearTimeout;
}

export interface HttpAdapterConfig extends HttpAdapterDependencies {
  baseUrl: string;
  eventStreamPath?: string;
  authToken?: string;
  maxReconnectAttempts?: number;
  initialReconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
}

function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

function redactToken(text: string, token: string | undefined): string {
  if (!token || !text) return text;
  return text.split(token).join("[redacted]");
}

function disconnectedEnvelope(): RuntimeSnapshotEnvelope {
  const t = new Date().toISOString();
  return {
    metadata: {
      runtimeId: "rt_disconnected",
      bootId: "boot_disconnected",
      revision: 0,
      sequence: 0,
      generatedAt: t,
      serverTimestamp: t,
      protocolId: RUNTIME_CONTRACT.protocolId,
      protocolVersion: RUNTIME_CONTRACT.protocolVersion,
      schemaVersion: RUNTIME_CONTRACT.schemaVersion,
      schemaHash: RUNTIME_CONTRACT.schemaHash,
      source: "LOCAL_RUNTIME",
    },
    snapshot: createEmptySnapshot(),
  };
}

function disabledCapabilities(): RuntimeCapabilities {
  const caps = buildCapabilities(createEmptySnapshot(), "LOCAL_RUNTIME");
  return {
    ...caps,
    commands: Object.fromEntries(
      Object.entries(caps.commands).map(([k, cap]) => [
        k,
        { ...cap, allowed: false, reason: "No local runtime connected." },
      ]),
    ) as RuntimeCapabilities["commands"],
  };
}

function disconnectedOperator(): OperatorIdentity {
  return {
    operatorId: "op_disconnected",
    displayName: "Disconnected",
    role: "VIEWER",
    sessionId: "sess_disconnected",
    authenticatedAt: "1970-01-01T00:00:00.000Z",
    simulated: false,
  };
}

export class HttpRuntimeAdapter implements RuntimeAdapter {
  readonly adapterType = "http" as const;

  private readonly baseUrl: string;
  private readonly eventStreamPath: string;
  private readonly authToken: string;
  private readonly fetchImpl: typeof fetch;
  private readonly EventSourceImpl: typeof EventSource | undefined;
  private readonly now: () => number;
  private readonly setTimeoutImpl: typeof setTimeout;
  private readonly clearTimeoutImpl: typeof clearTimeout;
  private readonly maxReconnectAttempts: number;
  private readonly initialReconnectDelayMs: number;
  private readonly maxReconnectDelayMs: number;

  private handshake: RuntimeHandshake | null = null;
  private capabilities: RuntimeCapabilities = disabledCapabilities();
  private envelope: RuntimeSnapshotEnvelope = disconnectedEnvelope();
  private connection: RuntimeConnectionStateSnapshot = {
    state: "DISCONNECTED",
    mode: "LOCAL_RUNTIME",
    adapterType: "http",
    reconnectAttempt: 0,
    errorMessage:
      "No local runtime connected. Start the local XDirga Runtime V4 and set VITE_RUNTIME_BASE_URL to connect. Target broker: Exness TRIAL.",
  };
  private operator: OperatorIdentity = disconnectedOperator();

  private snapshotListeners = new Set<(env: RuntimeSnapshotEnvelope) => void>();
  private eventListeners = new Set<(env: RuntimeEventEnvelope) => void>();
  private handshakeListeners = new Set<(h: RuntimeHandshake | null) => void>();
  private connectionListeners = new Set<(s: RuntimeConnectionStateSnapshot) => void>();
  private commandListeners = new Map<string, Set<(s: RuntimeCommandStatus) => void>>();
  private commandCache = new Map<string, RuntimeCommandStatus>();

  private dedup = new EventDeduplicator();
  private eventSource: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private staleTimer: ReturnType<typeof setTimeout> | null = null;
  private lastObservedAt = 0;
  private connectGeneration = 0;
  private intentionalDisconnect = false;
  private connecting = false;
  private lastSequence = 0;
  private sseBoundHandlers: Array<{ type: string; handler: (ev: MessageEvent) => void }> = [];

  constructor(config: HttpAdapterConfig) {
    this.baseUrl = config.baseUrl;
    this.eventStreamPath = config.eventStreamPath ?? "/events/stream";
    this.authToken = config.authToken ?? "";
    this.fetchImpl = config.fetch ?? fetch.bind(globalThis);
    this.EventSourceImpl =
      config.EventSource ?? (globalThis as { EventSource?: typeof EventSource }).EventSource;
    this.now = config.now ?? (() => Date.now());
    this.setTimeoutImpl = config.setTimeout ?? setTimeout.bind(globalThis);
    this.clearTimeoutImpl = config.clearTimeout ?? clearTimeout.bind(globalThis);
    this.maxReconnectAttempts = config.maxReconnectAttempts ?? 8;
    this.initialReconnectDelayMs = config.initialReconnectDelayMs ?? 250;
    this.maxReconnectDelayMs = config.maxReconnectDelayMs ?? 8_000;
  }

  private setConnection(partial: Partial<RuntimeConnectionStateSnapshot>) {
    this.connection = { ...this.connection, ...partial };
    for (const l of this.connectionListeners) l(this.connection);
  }

  private setHandshake(h: RuntimeHandshake | null) {
    this.handshake = h;
    for (const l of this.handshakeListeners) l(h);
  }

  private applySnapshot(env: RuntimeSnapshotEnvelope, seedDedup = true) {
    this.envelope = env;
    this.lastSequence = env.metadata.sequence;
    if (seedDedup) {
      const now = new Date(this.now()).toISOString();
      this.dedup.evaluate({
        eventId: `seed:${env.metadata.bootId}:${env.metadata.sequence}`,
        type: "runtime.state.changed",
        runtimeId: env.metadata.runtimeId,
        bootId: env.metadata.bootId,
        revision: env.metadata.revision,
        sequence: env.metadata.sequence,
        occurredAt: now,
        emittedAt: now,
        receivedAt: now,
        severity: "INFO",
        source: "LOCAL_RUNTIME",
        payload: {},
      });
    }
    for (const l of this.snapshotListeners) l(env);
  }

  private applyCapabilities(caps: RuntimeCapabilities) {
    this.capabilities = caps;
  }

  private restHeaders(): HeadersInit {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (this.authToken) {
      headers.Authorization = `Bearer ${this.authToken}`;
    }
    return headers;
  }

  private async restGet(path: string): Promise<unknown> {
    const url = joinUrl(this.baseUrl, path);
    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method: "GET",
        headers: this.restHeaders(),
      });
    } catch (e) {
      const msg = redactToken(e instanceof Error ? e.message : "network error", this.authToken);
      throw new Error(msg);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.text();
        detail = redactToken(body || detail, this.authToken);
      } catch {
        /* ignore */
      }
      throw new Error(redactToken(`Request failed: ${detail}`, this.authToken));
    }
    return res.json();
  }

  private async restPost(path: string, body: unknown): Promise<unknown> {
    const url = joinUrl(this.baseUrl, path);
    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method: "POST",
        headers: {
          ...this.restHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
    } catch (e) {
      const msg = redactToken(e instanceof Error ? e.message : "network error", this.authToken);
      throw new Error(msg);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const t = await res.text();
        detail = redactToken(t || detail, this.authToken);
      } catch {
        /* ignore */
      }
      throw new Error(redactToken(`Request failed: ${detail}`, this.authToken));
    }
    return res.json();
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer !== null) {
      this.clearTimeoutImpl(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private observeClientActivity() {
    this.lastObservedAt = this.now();
    if (this.staleTimer !== null) this.clearTimeoutImpl(this.staleTimer);
    this.staleTimer = this.setTimeoutImpl(() => {
      this.staleTimer = null;
      if (this.intentionalDisconnect || this.connection.state !== "CONNECTED") return;
      this.setConnection({
        state: "STALE",
        dataAgeMs: this.now() - this.lastObservedAt,
        errorMessage: "No observable stream activity within the client threshold.",
      });
    }, CLIENT_OBSERVATION_STALE_AFTER_MS);
  }

  private clearStaleTimer() {
    if (this.staleTimer !== null) {
      this.clearTimeoutImpl(this.staleTimer);
      this.staleTimer = null;
    }
  }

  private closeEventSource() {
    if (this.eventSource) {
      for (const { type, handler } of this.sseBoundHandlers) {
        try {
          this.eventSource.removeEventListener(type, handler as EventListener);
        } catch {
          /* ignore */
        }
      }
      this.sseBoundHandlers = [];
      try {
        this.eventSource.close();
      } catch {
        /* ignore */
      }
      this.eventSource = null;
    }
  }

  private buildStreamUrl(bootId: string, sequence: number): string {
    const path = joinUrl(this.baseUrl, this.eventStreamPath);
    const params = new URLSearchParams();
    params.set("bootId", bootId);
    params.set("sequence", String(sequence));
    if (this.authToken) params.set("token", this.authToken);
    return `${path}?${params.toString()}`;
  }

  private openEventSource(bootId: string, sequence: number, generation: number) {
    if (!this.EventSourceImpl) {
      throw new Error("EventSource is not available in this environment.");
    }
    this.closeEventSource();
    const url = this.buildStreamUrl(bootId, sequence);
    const es = new this.EventSourceImpl(url);
    this.eventSource = es;
    this.sseBoundHandlers = [];

    es.onopen = () => {
      if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
      this.setConnection({
        state: "CONNECTED",
        lastConnectedAt: new Date(this.now()).toISOString(),
        lastMessageAt: new Date(this.now()).toISOString(),
        reconnectAttempt: 0,
        errorMessage: undefined,
        errorCode: undefined,
        dataAgeMs: 0,
      });
      this.observeClientActivity();
    };

    for (const type of SSE_NAMED_TYPES) {
      const handler = (ev: MessageEvent) => {
        if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
        if (type === "system.resync.required") {
          void this.resyncSnapshot(generation);
          return;
        }
        void this.handleSseData(String(ev.data ?? ""), generation);
      };
      es.addEventListener(type, handler as EventListener);
      this.sseBoundHandlers.push({ type, handler });
    }

    es.onerror = () => {
      if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
      this.scheduleReconnect(generation);
    };
  }

  private async handleSseData(raw: string, generation: number) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    const validated = validateEnvelope(parsed);
    if (!validated.ok || !validated.envelope) return;
    const env = validated.envelope;
    const outcome = this.dedup.evaluate(env);

    if (outcome.action === "drop") return;

    if (outcome.action === "gap" || outcome.action === "reset-boot") {
      await this.resyncSnapshot(generation);
      return;
    }

    this.lastSequence = env.sequence;
    this.setConnection({
      state: "CONNECTED",
      lastMessageAt: new Date(this.now()).toISOString(),
      dataAgeMs: 0,
      errorMessage: undefined,
    });
    this.observeClientActivity();

    for (const l of this.eventListeners) l(env);
    this.scheduleSnapshotRefresh(generation);

    if (env.commandId && typeof env.payload === "object" && env.payload) {
      this.maybeApplyCommandEvent(env);
    }
  }

  private maybeApplyCommandEvent(env: RuntimeEventEnvelope) {
    const commandId = env.commandId;
    if (!commandId) return;
    const payload = env.payload as Record<string, unknown>;
    const nextState = typeof payload.state === "string" ? payload.state : undefined;
    const existing = this.commandCache.get(commandId);
    if (!existing || !nextState) return;
    const from = existing.state;
    const to = nextState as RuntimeCommandStatus["state"];
    if (!validateTransition(from, to).ok && from !== to) return;
    const updated: RuntimeCommandStatus = {
      ...existing,
      state: to,
      message: typeof payload.message === "string" ? payload.message : existing.message,
      reason: typeof payload.reason === "string" ? payload.reason : existing.reason,
      updatedAt: new Date(this.now()).toISOString(),
    };
    this.commandCache.set(commandId, updated);
    this.notifyCommand(commandId, updated);
  }

  private resyncInFlight = false;
  private snapshotRefreshScheduled = false;

  private scheduleSnapshotRefresh(generation: number) {
    if (this.snapshotRefreshScheduled) return;
    this.snapshotRefreshScheduled = true;
    queueMicrotask(() => {
      this.snapshotRefreshScheduled = false;
      void this.resyncSnapshot(generation, false);
    });
  }

  private async resyncSnapshot(generation: number, reopenStream = true) {
    if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
    if (this.resyncInFlight) return;
    this.resyncInFlight = true;
    try {
      const raw = (await this.restGet("/snapshot")) as RuntimeSnapshotEnvelope;
      if (generation !== this.connectGeneration || !raw?.metadata || !raw?.snapshot) return;
      this.applySnapshot(raw);
      if (reopenStream) this.openEventSource(raw.metadata.bootId, raw.metadata.sequence, generation);
    } catch {
      /* keep last accepted state */
    } finally {
      this.resyncInFlight = false;
    }
  }

  private scheduleReconnect(generation: number) {
    if (this.intentionalDisconnect || generation !== this.connectGeneration) return;
    this.clearStaleTimer();
    this.closeEventSource();
    const attempt = this.connection.reconnectAttempt + 1;
    if (attempt > this.maxReconnectAttempts) {
      this.setConnection({
        state: "ERROR",
        reconnectAttempt: attempt,
        errorCode: "RECONNECT_EXHAUSTED",
        errorMessage: "Reconnect attempts exhausted.",
        lastDisconnectedAt: new Date(this.now()).toISOString(),
      });
      return;
    }
    const delay = Math.min(
      this.maxReconnectDelayMs,
      this.initialReconnectDelayMs * 2 ** Math.max(0, attempt - 1),
    );
    this.setConnection({
      state: "RECONNECTING",
      reconnectAttempt: attempt,
      errorMessage: "Connection lost; reconnecting.",
    });
    this.clearReconnectTimer();
    this.reconnectTimer = this.setTimeoutImpl(() => {
      this.reconnectTimer = null;
      if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
      void this.reconnect(generation);
    }, delay);
  }

  private async reconnect(generation: number) {
    if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
    try {
      const hs = (await this.restGet("/handshake")) as RuntimeHandshake;
      if (generation !== this.connectGeneration) return;
      const compat = evaluateHandshake(hs);
      if (compat.safeMode) {
        this.setHandshake(hs);
        this.setConnection({
          state: "ERROR",
          errorCode: "HANDSHAKE_INCOMPATIBLE",
          errorMessage: compat.reasons[0]?.message ?? "Handshake incompatible.",
        });
        return;
      }
      this.setHandshake(hs);
      const caps = (await this.restGet("/capabilities")) as RuntimeCapabilities;
      if (generation !== this.connectGeneration) return;
      this.applyCapabilities(caps);
      const snap = (await this.restGet("/snapshot")) as RuntimeSnapshotEnvelope;
      if (generation !== this.connectGeneration) return;
      this.applySnapshot(snap);
      this.dedup.reset();
      this.openEventSource(hs.bootId, snap.metadata.sequence, generation);
    } catch (e) {
      if (generation !== this.connectGeneration || this.intentionalDisconnect) return;
      const msg = redactToken(e instanceof Error ? e.message : "reconnect failed", this.authToken);
      this.setConnection({
        state: "RECONNECTING",
        errorMessage: msg,
      });
      this.scheduleReconnect(generation);
    }
  }

  async connect(): Promise<void> {
    if (this.connecting) return;
    this.intentionalDisconnect = false;
    this.connecting = true;
    const generation = ++this.connectGeneration;
    this.clearReconnectTimer();
    this.clearStaleTimer();
    this.closeEventSource();
    this.dedup.reset();
    this.setConnection({
      state: "CONNECTING",
      reconnectAttempt: 0,
      errorMessage: undefined,
      errorCode: undefined,
    });
    try {
      const hs = (await this.restGet("/handshake")) as RuntimeHandshake;
      if (generation !== this.connectGeneration) return;
      this.setHandshake(hs);
      const compat = evaluateHandshake(hs);
      if (compat.safeMode) {
        this.setConnection({
          state: "ERROR",
          errorCode: "HANDSHAKE_INCOMPATIBLE",
          errorMessage: compat.reasons[0]?.message ?? "Handshake incompatible.",
        });
        throw new Error(compat.reasons[0]?.message ?? "Handshake incompatible.");
      }
      const caps = (await this.restGet("/capabilities")) as RuntimeCapabilities;
      if (generation !== this.connectGeneration) return;
      this.applyCapabilities(caps);
      const snap = (await this.restGet("/snapshot")) as RuntimeSnapshotEnvelope;
      if (generation !== this.connectGeneration) return;
      if (!snap?.metadata || !snap?.snapshot) {
        throw new Error("Invalid snapshot response.");
      }
      this.applySnapshot(snap);
      this.operator = {
        operatorId: "op_local_runtime",
        displayName: "Local Runtime",
        role: "OPERATOR",
        sessionId: `sess_${hs.bootId}`,
        authenticatedAt: hs.observedAt,
        simulated: false,
      };
      this.openEventSource(hs.bootId, snap.metadata.sequence, generation);
    } catch (e) {
      if (generation === this.connectGeneration) {
        const msg = redactToken(e instanceof Error ? e.message : "connect failed", this.authToken);
        this.setConnection({
          state: "ERROR",
          errorMessage: msg,
          lastDisconnectedAt: new Date(this.now()).toISOString(),
        });
      }
      throw e instanceof Error ? new Error(redactToken(e.message, this.authToken)) : e;
    } finally {
      this.connecting = false;
    }
  }

  async disconnect(): Promise<void> {
    this.intentionalDisconnect = true;
    this.connectGeneration += 1;
    this.clearReconnectTimer();
    this.clearStaleTimer();
    this.closeEventSource();
    this.setConnection({
      state: "DISCONNECTED",
      reconnectAttempt: 0,
      lastDisconnectedAt: new Date(this.now()).toISOString(),
      errorMessage: "Disconnected.",
    });
  }

  getSnapshot(): CockpitSnapshot {
    return this.envelope.snapshot;
  }

  getSnapshotEnvelope(): RuntimeSnapshotEnvelope {
    return this.envelope;
  }

  async refreshSnapshot(): Promise<RuntimeSnapshotEnvelope> {
    const raw = (await this.restGet("/snapshot")) as RuntimeSnapshotEnvelope;
    if (!raw?.metadata || !raw?.snapshot) {
      throw new Error("Invalid snapshot response.");
    }
    this.applySnapshot(raw);
    return raw;
  }

  subscribeSnapshot(listener: (env: RuntimeSnapshotEnvelope) => void): () => void {
    this.snapshotListeners.add(listener);
    return () => {
      this.snapshotListeners.delete(listener);
    };
  }

  subscribeEvents(listener: (env: RuntimeEventEnvelope) => void): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  getCapabilities(): RuntimeCapabilities {
    return this.capabilities;
  }

  async refreshCapabilities(): Promise<RuntimeCapabilities> {
    const caps = (await this.restGet("/capabilities")) as RuntimeCapabilities;
    this.applyCapabilities(caps);
    return caps;
  }

  getHandshake(): RuntimeHandshake | null {
    return this.handshake;
  }

  async refreshHandshake(): Promise<RuntimeHandshake> {
    const hs = (await this.restGet("/handshake")) as RuntimeHandshake;
    this.setHandshake(hs);
    return hs;
  }

  subscribeHandshake(listener: (h: RuntimeHandshake | null) => void): () => void {
    this.handshakeListeners.add(listener);
    return () => {
      this.handshakeListeners.delete(listener);
    };
  }

  async submitCommand(_request: RuntimeCommandRequest): Promise<CommandAccepted> {
    void _request;
    throw new Error("Commands are available only in the development fixture.");
  }

  async getCommand(_commandId: string): Promise<RuntimeCommandStatus> {
    void _commandId;
    throw new Error("Commands are available only in the development fixture.");
  }

  subscribeCommand(commandId: string, listener: (s: RuntimeCommandStatus) => void): () => void {
    let set = this.commandListeners.get(commandId);
    if (!set) {
      set = new Set();
      this.commandListeners.set(commandId, set);
    }
    set.add(listener);
    return () => {
      set!.delete(listener);
      if (set!.size === 0) this.commandListeners.delete(commandId);
    };
  }

  private notifyCommand(commandId: string, status: RuntimeCommandStatus) {
    const set = this.commandListeners.get(commandId);
    if (!set) return;
    for (const l of set) l(status);
  }

  async getTradeHistory(query?: TradeHistoryQuery): Promise<TradeHistoryPage> {
    const params = new URLSearchParams();
    if (query?.cursor != null && query.cursor !== "") {
      params.set("cursor", query.cursor);
    }
    if (query?.limit != null) {
      params.set("limit", String(query.limit));
    }
    const qs = params.toString();
    const path = qs ? `/history/trades?${qs}` : "/history/trades";
    const url = joinUrl(this.baseUrl, path.split("?")[0]) + (qs ? `?${qs}` : "");
    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method: "GET",
        headers: this.restHeaders(),
      });
    } catch (e) {
      throw new Error(
        redactToken(e instanceof Error ? e.message : "network error", this.authToken),
      );
    }
    if (!res.ok) {
      throw new Error(redactToken(`Request failed: HTTP ${res.status}`, this.authToken));
    }
    const raw = (await res.json()) as TradeHistoryPage;
    return {
      trades: Array.isArray(raw?.trades) ? raw.trades : [],
      nextCursor: raw?.nextCursor ?? null,
    };
  }

  getConnectionState(): RuntimeConnectionStateSnapshot {
    return this.connection;
  }

  subscribeConnection(listener: (s: RuntimeConnectionStateSnapshot) => void): () => void {
    this.connectionListeners.add(listener);
    return () => {
      this.connectionListeners.delete(listener);
    };
  }

  getOperator(): OperatorIdentity {
    return this.operator;
  }

  getDescriptor(): RuntimeAdapterDescriptor {
    return {
      adapterType: "HTTP_LOCAL_RUNTIME",
      dataSource: "LOCAL_RUNTIME",
      isDevelopmentOnly: false,
    };
  }

  isDevelopmentFixture(): boolean {
    return false;
  }

  isDemo(): boolean {
    return false;
  }
}
