import type {
  Alert,
  BrokerStatus,
  CircuitBreaker,
  ClosedTrade,
  CockpitSnapshot,
  EquityPoint,
  Incident,
  MarketSymbol,
  Order,
  Position,
  ReconciliationSummary,
  RiskLimit,
  RuntimeEvent,
  RuntimeStatus,
  ScenarioKey,
  Strategy,
  SubsystemHealth,
  TradeExitReason,
} from "@/lib/types";

// Deterministic timestamps so snapshots are stable across renders (no fake tick animation).
const NOW = new Date("2026-07-11T14:32:18.000Z");
const iso = (offsetSec: number) => new Date(NOW.getTime() + offsetSec * 1000).toISOString();

function seq(n: number) {
  return Array.from({ length: n }, (_, i) => i);
}

function baseRuntime(overrides: Partial<RuntimeStatus> = {}): RuntimeStatus {
  return {
    id: "rt_local_01HXDRG4",
    sessionId: "sess_2026_07_11_a",
    version: "4.0.0-rc.3",
    buildHash: "9a7c3f1",
    environment: "LOCAL",
    tradingMode: "TRIAL",
    state: "READY",
    previousState: "RECONCILING",
    stateChangedAt: iso(-1820),
    stateReason: "Reconciliation completed. All entities in sync.",
    startedAt: iso(-17400),
    uptimeSec: 17400,
    lastHeartbeatAt: iso(-2),
    heartbeatLatencyMs: 8,
    entriesEnabled: true,
    automationEnabled: true,
    hostname: "trader-01.local",
    os: "macOS 15.4",
    pid: 48291,
    ...overrides,
  };
}

function baseBroker(overrides: Partial<BrokerStatus> = {}): BrokerStatus {
  return {
    broker: "Broker-XM",
    server: "XM-Real-07",
    loginMasked: "•••• 4419",
    accountMode: "TRIAL",
    connection: "CONNECTED",
    tradingPermitted: true,
    terminalVersion: "MT5 build 4620",
    lastTickAt: iso(-1),
    lastRequestAt: iso(-4),
    queueDepth: 0,
    avgLatencyMs: 42,
    timeoutCount: 0,
    reconnectAttempts: 0,
    ...overrides,
  };
}

function healthySubsystems(): SubsystemHealth[] {
  const rows: Array<[string, string]> = [
    ["runtime", "Runtime Process"],
    ["broker", "Broker Gateway"],
    ["market", "Market Data"],
    ["strategy", "Strategy Engine"],
    ["execution", "Execution Engine"],
    ["risk", "Risk Engine"],
    ["db", "Local Database"],
    ["ws", "WebSocket Bus"],
    ["recon", "Reconciliation"],
    ["telemetry", "Telemetry"],
  ];
  return rows.map(([key, label], i) => ({
    key,
    label,
    state: "OK",
    lastHeartbeatAt: iso(-((i % 6) + 1)),
    latencyMs: 6 + (i % 5) * 3,
    restartCount: 0,
    currentAction: null,
    lastError: null,
  }));
}

const STRATEGIES: Strategy[] = [
  {
    id: "strat_xdrg_trend_v3",
    name: "XDRG Trend Continuation",
    version: "3.4.1",
    symbols: ["EURUSD", "GBPUSD"],
    timeframe: "M15",
    status: "ACTIVE",
    tradingMode: "TRIAL",
    entriesEnabled: true,
    allocationPct: 45,
    pnlToday: 218.42,
    drawdown: -0.6,
    signalsToday: 14,
    lastSignalAt: iso(-320),
    lastExecutionAt: iso(-780),
    currentBias: "LONG",
    confidence: 0.72,
    openPositions: 2,
    health: "OK",
  },
  {
    id: "strat_xdrg_meanrev_v2",
    name: "XDRG Mean Reversion",
    version: "2.9.0",
    symbols: ["XAUUSD"],
    timeframe: "M5",
    status: "PAUSED",
    tradingMode: "TRIAL",
    entriesEnabled: false,
    allocationPct: 25,
    pnlToday: -46.1,
    drawdown: -1.4,
    signalsToday: 6,
    lastSignalAt: iso(-1900),
    lastExecutionAt: iso(-8600),
    currentBias: "FLAT",
    confidence: 0.31,
    openPositions: 0,
    health: "DEGRADED",
  },
  {
    id: "strat_xdrg_breakout_v1",
    name: "XDRG Session Breakout",
    version: "1.6.2",
    symbols: ["US30", "NAS100"],
    timeframe: "M30",
    status: "IDLE",
    tradingMode: "TRIAL",
    entriesEnabled: true,
    allocationPct: 20,
    pnlToday: 0,
    drawdown: 0,
    signalsToday: 0,
    lastSignalAt: null,
    lastExecutionAt: iso(-72000),
    currentBias: "FLAT",
    confidence: 0.5,
    openPositions: 0,
    health: "OK",
  },
  {
    id: "strat_xdrg_carry_v1",
    name: "XDRG Carry Rotation",
    version: "1.0.0",
    symbols: ["AUDJPY", "NZDJPY"],
    timeframe: "H1",
    status: "WARMING_UP",
    tradingMode: "TRIAL",
    entriesEnabled: false,
    allocationPct: 10,
    pnlToday: 0,
    drawdown: 0,
    signalsToday: 0,
    lastSignalAt: null,
    lastExecutionAt: null,
    currentBias: "FLAT",
    confidence: 0.4,
    openPositions: 0,
    health: "OK",
  },
];

// -----------------------------------------------------------------------------
// Position fixtures. Sign convention (see src/lib/types.ts):
//   commission and swap are SIGNED as reported by MT5.
//   netPnl = floatingPnl + commission + swap  (addition, not subtraction).
// -----------------------------------------------------------------------------
const POSITIONS: Position[] = [
  {
    id: "pos_01HXDRG5A",
    brokerTicket: "884120391",
    ownership: "BOT_MANAGED",
    dataAvailable: true,
    sourceFrameId: 1,
    observedAt: iso(-4),
    symbol: "EURUSD",
    side: "BUY",
    volume: 0.5,
    entryPrice: 1.0842,
    currentPrice: 1.08611,
    stopLoss: 1.0812,
    takeProfit: 1.0912,
    floatingPnl: 95.5,
    realizedPnl: 0,
    riskAmount: 150,
    riskPct: 0.6,
    openedAt: iso(-4200),
    strategy: "XDRG Trend Continuation",
    protection: "PROTECTED",
    state: "OPEN",
    rMultiple: 0.64,
    mfe: 132,
    mae: -28,
    commission: -3.5, // broker cost, negative
    swap: -0.42,       // negative overnight funding
    netPnl: 95.5 + -3.5 + -0.42, // 91.58 — identity: net = floating + commission + swap
    management: {
      planId: "mp_01HXDRG_A",
      source: "STRATEGY",
      breakEven: {
        enabled: true,
        triggerR: 1.0,
        offsetPoints: 12,
        state: "PENDING",
        appliedAt: null,
      },
      trailing: {
        mode: "ATR",
        active: false,
        distancePoints: null,
        currentStopPrice: null,
        lastMovedAt: null,
        moveCount: 0,
      },
      partialTp: {
        levels: [
          {
            levelId: "tp_1r",
            atR: 1.0,
            closePercent: 33,
            state: "PENDING",
            executedAt: null,
            executedPrice: null,
            closedVolume: null,
          },
          {
            levelId: "tp_2r",
            atR: 2.0,
            closePercent: 33,
            state: "PENDING",
            executedAt: null,
            executedPrice: null,
            closedVolume: null,
          },
        ],
      },
      timeExit: { maxHoldUntil: iso(6 * 3600), state: "PENDING" },
      nextAction: "Arm BE stop when bid ≥ 1.08650 (offset +12pt above entry).",
      lastError: null,
      paused: false,
    },
  },
  {
    id: "pos_01HXDRG5B",
    brokerTicket: "884120442",
    ownership: "BOT_MANAGED",
    dataAvailable: true,
    sourceFrameId: 1,
    observedAt: iso(-4),
    symbol: "GBPUSD",
    side: "BUY",
    volume: 0.3,
    entryPrice: 1.2701,
    currentPrice: 1.27182,
    stopLoss: 1.2681,
    takeProfit: 1.2761,
    floatingPnl: 51.6,
    realizedPnl: 0,
    riskAmount: 60,
    riskPct: 0.24,
    openedAt: iso(-2600),
    strategy: "XDRG Trend Continuation",
    protection: "PROTECTED",
    state: "OPEN",
    rMultiple: 0.86,
    mfe: 71,
    mae: -12,
    commission: -2.1,
    swap: 0.08, // occasional positive credit
    netPnl: 51.6 + -2.1 + 0.08,
    management: {
      planId: "mp_01HXDRG_B",
      source: "STRATEGY",
      breakEven: {
        enabled: true,
        triggerR: 0.8,
        offsetPoints: 8,
        state: "APPLIED",
        appliedAt: iso(-1200),
      },
      trailing: {
        mode: "STEP",
        active: true,
        distancePoints: 20,
        currentStopPrice: 1.27015,
        lastMovedAt: iso(-600),
        moveCount: 2,
      },
      partialTp: {
        levels: [
          {
            levelId: "tp_1r",
            atR: 1.0,
            closePercent: 40,
            state: "PENDING",
            executedAt: null,
            executedPrice: null,
            closedVolume: null,
          },
        ],
      },
      timeExit: { maxHoldUntil: null, state: "DISABLED" },
      nextAction: "Trail SL to 1.27085 when bid ≥ 1.27285.",
      lastError: null,
      paused: false,
    },
  },
  {
    id: "pos_01HXDRG5C",
    brokerTicket: "884120510",
    ownership: "UNKNOWN",
    dataAvailable: true,
    sourceFrameId: 1,
    observedAt: iso(-4),
    symbol: "XAUUSD",
    side: "SELL",
    volume: 0.1,
    entryPrice: 2411.2,
    currentPrice: 2415.83,
    stopLoss: null,
    takeProfit: 2401,
    floatingPnl: -46.3,
    realizedPnl: 0,
    riskAmount: 0,
    riskPct: 0,
    openedAt: iso(-9100),
    strategy: "XDRG Mean Reversion",
    protection: "UNPROTECTED",
    state: "OPEN",
    rMultiple: -0.34,
    mfe: 18,
    mae: -62,
    commission: -1.2,
    swap: -3.15,
    netPnl: -46.3 + -1.2 + -3.15,
    // Manual override position with no active autopilot plan.
    management: null,
  },
];

const ORDERS: Order[] = [
  {
    id: "ord_01HXDRG6A",
    brokerTicket: "884120391",
    clientRequestId: "req_1720705018_884",
    correlationId: "corr_a1b2c3",
    symbol: "EURUSD",
    side: "BUY",
    type: "MARKET",
    volume: 0.5,
    requestedPrice: 1.0842,
    filledPrice: 1.0842,
    stopLoss: 1.0812,
    takeProfit: 1.0912,
    slippage: 0,
    strategy: "XDRG Trend Continuation",
    createdAt: iso(-4210),
    updatedAt: iso(-4200),
    status: "FILLED",
    rejectionReason: null,
    lifecycle: [
      { at: iso(-4211), step: "CREATED", detail: "Signal accepted from strategy" },
      { at: iso(-4210), step: "RISK_CHECKED", detail: "0.6% risk within 2% budget", latencyMs: 3 },
      { at: iso(-4210), step: "SAFETY_CHECKED", detail: "All breakers CLOSED", latencyMs: 2 },
      { at: iso(-4209), step: "SUBMITTED", detail: "Sent to broker gateway" },
      { at: iso(-4208), step: "BROKER_ACK", detail: "MT5 acknowledged", latencyMs: 41 },
      { at: iso(-4200), step: "FILLED", detail: "Filled @ 1.08420 (0 pips slippage)" },
    ],
  },
  {
    id: "ord_01HXDRG6B",
    brokerTicket: null,
    clientRequestId: "req_1720705988_112",
    correlationId: "corr_d4e5f6",
    symbol: "USDJPY",
    side: "SELL",
    type: "LIMIT",
    volume: 0.2,
    requestedPrice: 158.42,
    filledPrice: null,
    stopLoss: 158.72,
    takeProfit: 157.82,
    slippage: null,
    strategy: "XDRG Trend Continuation",
    createdAt: iso(-1100),
    updatedAt: iso(-1090),
    status: "ACKNOWLEDGED",
    rejectionReason: null,
    lifecycle: [
      { at: iso(-1101), step: "CREATED", detail: "Pending limit order" },
      { at: iso(-1100), step: "SUBMITTED", detail: "Sent to broker" },
      { at: iso(-1090), step: "ACKNOWLEDGED", detail: "Working @ 158.420", latencyMs: 55 },
    ],
  },
  {
    id: "ord_01HXDRG6C",
    brokerTicket: null,
    clientRequestId: "req_1720705912_301",
    correlationId: "corr_g7h8i9",
    symbol: "XAUUSD",
    side: "BUY",
    type: "MARKET",
    volume: 0.05,
    requestedPrice: 2415.4,
    filledPrice: null,
    stopLoss: null,
    takeProfit: null,
    slippage: null,
    strategy: "XDRG Mean Reversion",
    createdAt: iso(-620),
    updatedAt: iso(-610),
    status: "REJECTED",
    rejectionReason: "Spread exceeded breaker threshold (12.4 vs max 8.0)",
    lifecycle: [
      { at: iso(-621), step: "CREATED", detail: "Signal accepted" },
      { at: iso(-620), step: "SAFETY_CHECKED", detail: "Excess spread breaker WARNING" },
      { at: iso(-610), step: "REJECTED", detail: "Blocked by safety engine" },
    ],
  },
];

const MARKETS: MarketSymbol[] = [
  ["EURUSD", "FX", 1.0861, 1.08612, 1.0861, 0.12, 20, 100000, 0.00001, 0.01, 100, 0.01, -6.2, 1.4, 3.33],
  ["GBPUSD", "FX", 1.27178, 1.27185, 1.27182, 0.32, 34, 100000, 0.00001, 0.01, 50, 0.01, -8.4, 2.1, 3.33],
  ["USDJPY", "FX", 158.412, 158.418, 158.415, -0.18, 24, 100000, 0.001, 0.01, 50, 0.01, 5.2, -12.1, 3.33],
  ["AUDJPY", "FX", 104.612, 104.622, 104.617, null, 60, 100000, 0.001, 0.01, 50, 0.01, 1.1, -3.4, 3.33],
  ["XAUUSD", "METALS", 2415.71, 2415.94, 2415.83, 0.42, 210, 100, 0.01, 0.01, 100, 0.01, -18.2, -22.4, 5],
  ["US30", "INDICES", 39821.4, 39825.2, 39823.3, -0.22, 850, 1, 0.1, 0.1, 100, 0.1, -2.1, -1.4, 1],
  ["NAS100", "INDICES", 20114.2, 20117.8, 20116.0, 0.11, 610, 1, 0.1, 0.1, 100, 0.1, -3.2, -2.4, 1],
  ["BTCUSD", "CRYPTO", 118420.1, 118472.4, 118446.2, 1.42, 4200, 1, 0.01, 0.01, 10, 0.01, 0, 0, 20],
].map(
  ([symbol, group, bid, ask, last, changePct, tickAgeMs, contractSize, tickSize, minVolume, maxVolume, volumeStep, swapLong, swapShort, marginRequirement]) => ({
    symbol: symbol as string,
    group: group as MarketSymbol["group"],
    bid: bid as number,
    ask: ask as number,
    spread: +((ask as number) - (bid as number)).toFixed(5),
    last: last as number,
    changePct: changePct as number | null,
    sessionOpen: true,
    tradingPermitted: true,
    tickAgeMs: tickAgeMs as number,
    freshness: ((tickAgeMs as number) > 5000 ? "STALE" : "FRESH") as MarketSymbol["freshness"],
    contractSize: contractSize as number,
    tickSize: tickSize as number,
    minVolume: minVolume as number,
    maxVolume: maxVolume as number,
    volumeStep: volumeStep as number,
    swapLong: swapLong as number,
    swapShort: swapShort as number,
    marginRequirement: marginRequirement as number,
  }),
);

const ALERTS: Alert[] = [
  {
    id: "alert_01",
    severity: "HIGH",
    title: "Position XAUUSD lacks stop-loss protection",
    source: "Risk Engine",
    createdAt: iso(-9080),
    description:
      "Position pos_01HXDRG5C on XAUUSD has been running for 2h 31m without a broker-side stop-loss.",
    suggestedAction: "Attach protection or request controlled close.",
    acknowledged: false,
  },
  {
    id: "alert_02",
    severity: "MEDIUM",
    title: "Strategy 'XDRG Mean Reversion' degraded",
    source: "Strategy Engine",
    createdAt: iso(-1900),
    description: "Signal quality below threshold for 3 consecutive evaluation windows.",
    suggestedAction: "Review indicator inputs. Strategy is auto-paused.",
    acknowledged: false,
  },
  {
    id: "alert_03",
    severity: "LOW",
    title: "Broker latency elevated",
    source: "Broker Gateway",
    createdAt: iso(-320),
    description: "Rolling p95 latency 118ms (baseline 60ms). Still within trading tolerance.",
    suggestedAction: "Monitor. No action required.",
    acknowledged: true,
  },
];

const INCIDENTS: Incident[] = [
  {
    id: "inc_2026_0711_01",
    severity: "HIGH",
    status: "INVESTIGATING",
    title: "Elevated broker request timeouts",
    startedAt: iso(-5400),
    durationSec: 5400,
    source: "Broker Gateway",
    impact: "Order acknowledgement latency increased. No missed fills.",
    affectedComponents: ["Broker Gateway", "Execution Engine"],
    rootCause: null,
    resolution: null,
  },
  {
    id: "inc_2026_0710_04",
    severity: "MEDIUM",
    status: "RESOLVED",
    title: "Market data feed lag on XAUUSD",
    startedAt: iso(-86400),
    durationSec: 720,
    source: "Market Data",
    impact: "Ticks delayed up to 4s. Strategies auto-paused.",
    affectedComponents: ["Market Data"],
    rootCause: "Upstream WebSocket restart",
    resolution: "Reconnected. Backfill completed.",
  },
];

const RISK_LIMITS: RiskLimit[] = [
  { key: "daily_loss", label: "Max Daily Loss", configured: 500, current: 46.1, unit: "USD", warnAt: 350, breachAt: 500, breached: false, changedAt: iso(-172800), changedBy: "operator@local" },
  { key: "weekly_loss", label: "Max Weekly Loss", configured: 1500, current: 218.4, unit: "USD", warnAt: 1000, breachAt: 1500, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "drawdown", label: "Max Drawdown", configured: 5, current: 1.4, unit: "PCT", warnAt: 3, breachAt: 5, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "gross_exposure", label: "Max Gross Exposure", configured: 100000, current: 62410, unit: "USD", warnAt: 80000, breachAt: 100000, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "open_positions", label: "Max Open Positions", configured: 8, current: 3, unit: "COUNT", warnAt: 6, breachAt: 8, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "risk_per_trade", label: "Max Risk / Trade", configured: 1, current: 0.6, unit: "PCT", warnAt: 0.8, breachAt: 1, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "consecutive_losses", label: "Max Consecutive Losses", configured: 4, current: 1, unit: "COUNT", warnAt: 3, breachAt: 4, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "max_slippage", label: "Max Slippage", configured: 5, current: 0.4, unit: "PRICE", warnAt: 3, breachAt: 5, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "max_spread", label: "Max Spread", configured: 8, current: 3.2, unit: "PRICE", warnAt: 6, breachAt: 8, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "min_margin_level", label: "Min Margin Level", configured: 300, current: 1240, unit: "PCT", warnAt: 500, breachAt: 300, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "max_order_latency", label: "Max Order Latency", configured: 2000, current: 42, unit: "MS", warnAt: 800, breachAt: 2000, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
  { key: "max_data_age", label: "Max Market Data Age", configured: 5000, current: 210, unit: "MS", warnAt: 2000, breachAt: 5000, breached: false, changedAt: iso(-604800), changedBy: "operator@local" },
];

const BREAKERS: CircuitBreaker[] = [
  { key: "broker_disconnect", label: "Broker Disconnect", state: "CLOSED", triggerCondition: ">3s no heartbeat", currentValue: "1s", threshold: "3s", triggeredAt: null, recoveryCondition: "Stable connection for 30s", manualResetAllowed: false, lastResetAt: null },
  { key: "market_stale", label: "Market Data Stale", state: "CLOSED", triggerCondition: ">5s tick age", currentValue: "210ms", threshold: "5s", triggeredAt: null, recoveryCondition: "<1s tick age for 15s", manualResetAllowed: false, lastResetAt: null },
  { key: "excess_spread", label: "Excess Spread", state: "WARNING", triggerCondition: "spread > max", currentValue: "6.1", threshold: "8.0", triggeredAt: null, recoveryCondition: "Spread < 4.0", manualResetAllowed: true, lastResetAt: iso(-72000) },
  { key: "daily_loss", label: "Daily Loss", state: "CLOSED", triggerCondition: "loss > daily limit", currentValue: "$46.10", threshold: "$500.00", triggeredAt: null, recoveryCondition: "Session reset", manualResetAllowed: false, lastResetAt: null },
  { key: "drawdown", label: "Drawdown", state: "CLOSED", triggerCondition: "drawdown > max", currentValue: "1.4%", threshold: "5.0%", triggeredAt: null, recoveryCondition: "New equity high", manualResetAllowed: false, lastResetAt: null },
  { key: "margin", label: "Margin", state: "CLOSED", triggerCondition: "margin level < min", currentValue: "1240%", threshold: "300%", triggeredAt: null, recoveryCondition: "margin > 500%", manualResetAllowed: false, lastResetAt: null },
  { key: "exec_timeout", label: "Execution Timeout", state: "CLOSED", triggerCondition: ">2s no ack", currentValue: "42ms", threshold: "2000ms", triggeredAt: null, recoveryCondition: "3 successful acks", manualResetAllowed: true, lastResetAt: null },
  { key: "repeat_reject", label: "Repeated Rejection", state: "WARNING", triggerCondition: "3+ rejects / 5m", currentValue: "2", threshold: "3", triggeredAt: null, recoveryCondition: "5m clean window", manualResetAllowed: true, lastResetAt: null },
  { key: "recon_fail", label: "Reconciliation Failure", state: "CLOSED", triggerCondition: "2 consecutive failures", currentValue: "0", threshold: "2", triggeredAt: null, recoveryCondition: "Successful reconciliation", manualResetAllowed: true, lastResetAt: null },
  { key: "strategy_error", label: "Strategy Error", state: "CLOSED", triggerCondition: "unhandled exception", currentValue: "0", threshold: "1", triggeredAt: null, recoveryCondition: "Manual reset", manualResetAllowed: true, lastResetAt: null },
  { key: "runtime_health", label: "Runtime Health", state: "CLOSED", triggerCondition: "any subsystem DOWN", currentValue: "OK", threshold: "OK", triggeredAt: null, recoveryCondition: "All subsystems OK", manualResetAllowed: false, lastResetAt: null },
];

const RECONCILIATION: ReconciliationSummary = {
  state: "OK",
  lastRunAt: iso(-180),
  brokerOrders: 12,
  runtimeOrders: 12,
  brokerPositions: 3,
  runtimePositions: 3,
  missingOrders: 0,
  unknownOrders: 0,
  positionMismatches: 0,
  volumeMismatches: 0,
  stateMismatches: 0,
  issues: [],
};

const EVENTS: RuntimeEvent[] = [
  { id: "evt_10", at: iso(-4), severity: "INFO", source: "runtime", component: "heartbeat", message: "Heartbeat OK (8ms)" },
  { id: "evt_09", at: iso(-180), severity: "INFO", source: "recon", component: "reconciliation", message: "Reconciliation completed. 0 issues.", correlationId: "corr_recon_881" },
  { id: "evt_08", at: iso(-320), severity: "WARNING", source: "broker", component: "gateway", message: "Broker latency elevated: 118ms p95" },
  { id: "evt_07", at: iso(-610), severity: "ERROR", source: "safety", component: "excess_spread", message: "Order rejected by excess spread breaker", orderId: "ord_01HXDRG6C", symbol: "XAUUSD" },
  { id: "evt_06", at: iso(-780), severity: "INFO", source: "execution", component: "fill", message: "Order filled EURUSD 0.5 lots @ 1.08420", orderId: "ord_01HXDRG6A", strategy: "XDRG Trend Continuation" },
  { id: "evt_05", at: iso(-1090), severity: "INFO", source: "broker", component: "ack", message: "Limit order acknowledged USDJPY 0.2 @ 158.420", orderId: "ord_01HXDRG6B" },
  { id: "evt_04", at: iso(-1820), severity: "INFO", source: "runtime", component: "state", message: "Runtime transitioned RECONCILING → READY" },
  { id: "evt_03", at: iso(-1900), severity: "WARNING", source: "strategy", component: "xdrg_meanrev", message: "Strategy paused: signal quality below threshold", strategy: "XDRG Mean Reversion" },
  { id: "evt_02", at: iso(-9080), severity: "WARNING", source: "risk", component: "protection", message: "Unprotected position detected", positionId: "pos_01HXDRG5C", symbol: "XAUUSD" },
  { id: "evt_01", at: iso(-17400), severity: "INFO", source: "runtime", component: "boot", message: "Runtime started, version 4.0.0-rc.3" },
];

const EQUITY: EquityPoint[] = seq(48).map((i) => {
  const t = -47 + i;
  const drift = Math.sin(i / 4) * 60 + i * 4;
  const equity = 25000 + drift;
  const balance = 25000 + Math.max(0, i * 3);
  return {
    at: iso(t * 1800),
    equity: +equity.toFixed(2),
    balance: +balance.toFixed(2),
    floatingPnl: +(equity - balance).toFixed(2),
    drawdown: +Math.min(0, drift - Math.max(...seq(i + 1).map((k) => Math.sin(k / 4) * 60 + k * 4))).toFixed(2),
  };
});

function accountFor(scenario: ScenarioKey) {
  const base = {
    currency: "USD",
    balance: 25188.42,
    equity: 25289.22,
    margin: 620.4,
    freeMargin: 24668.82,
    marginLevel: 1240,
    floatingPnl: 100.8,
    realizedPnlToday: 218.42,
    realizedPnlWeek: 812.55,
    dailyDrawdown: -46.1,
    maxDrawdown: -3.4,
    grossExposure: 62410,
    netExposure: 41120,
    openPositions: 3,
    pendingOrders: 1,
    tradesToday: 14,
    winRate: 61.4,
    profitFactor: 1.82,
    riskUtilization: 42,
    updatedAt: iso(-2),
    freshness: "FRESH" as const,
  };
  if (scenario === "drawdown") {
    return { ...base, equity: 24102, floatingPnl: -410, dailyDrawdown: -412, maxDrawdown: -6.8, realizedPnlToday: -380, riskUtilization: 92, freshness: "FRESH" as const };
  }
  if (scenario === "brokerDown") {
    return { ...base, freshness: "STALE" as const, updatedAt: iso(-180) };
  }
  return base;
}

export function buildSnapshot(scenario: ScenarioKey): CockpitSnapshot {
  const subsystems = healthySubsystems();
  let runtime = baseRuntime();
  let broker = baseBroker();
  let reconciliation = RECONCILIATION;
  let alerts = [...ALERTS];
  let orders = [...ORDERS];

  switch (scenario) {
    case "degraded":
      runtime = baseRuntime({ state: "DEGRADED", stateReason: "Broker gateway latency exceeds warning threshold." });
      subsystems[1] = { ...subsystems[1], state: "DEGRADED", latencyMs: 240, lastError: "p95 latency > 200ms" };
      broker = baseBroker({ connection: "DEGRADED", avgLatencyMs: 240, timeoutCount: 3 });
      break;
    case "brokerDown":
      runtime = baseRuntime({ state: "RECONNECTING", stateReason: "Broker connection lost. Attempting reconnect." });
      subsystems[1] = { ...subsystems[1], state: "DOWN", latencyMs: null, lastError: "Connection closed by peer", currentAction: "reconnect_attempt=3" };
      subsystems[2] = { ...subsystems[2], state: "DEGRADED", lastError: "No ticks for 12s" };
      broker = baseBroker({ connection: "RECONNECTING", tradingPermitted: false, queueDepth: 4, reconnectAttempts: 3, avgLatencyMs: 0 });
      alerts = [
        {
          id: "alert_critical",
          severity: "CRITICAL",
          title: "Broker gateway disconnected",
          source: "Broker Gateway",
          createdAt: iso(-14),
          description: "MT5 terminal connection lost. Automated trading suspended.",
          suggestedAction: "Verify terminal, then Reconnect Broker from Runtime page.",
          acknowledged: false,
        },
        ...alerts,
      ];
      break;
    case "reconciling":
      runtime = baseRuntime({ state: "RECONCILING", stateReason: "Recovering session state from broker." });
      reconciliation = {
        ...RECONCILIATION,
        state: "RUNNING",
        brokerOrders: 12,
        runtimeOrders: 11,
        missingOrders: 1,
        issues: [
          {
            entity: "ORDER",
            entityId: "884120677",
            runtimeState: "UNKNOWN",
            brokerState: "FILLED",
            difference: "Runtime missing execution record",
            severity: "HIGH",
            suggestedAction: "Import broker record into runtime store",
            resolved: false,
          },
        ],
      };
      break;
    case "paused":
      runtime = baseRuntime({ state: "PAUSED", entriesEnabled: false, automationEnabled: false, stateReason: "Operator paused runtime." });
      break;
    case "killed":
      runtime = baseRuntime({ state: "KILLED", entriesEnabled: false, automationEnabled: false, stateReason: "Emergency kill executed by operator." });
      subsystems.forEach((s, i) => (subsystems[i] = { ...s, state: i === 0 ? "OK" : "DOWN", currentAction: "halted" }));
      broker = baseBroker({ connection: "DISCONNECTED", tradingPermitted: false });
      break;
    case "drawdown":
      runtime = baseRuntime({ state: "DEGRADED", entriesEnabled: false, stateReason: "Daily loss breaker WARNING." });
      alerts = [
        {
          id: "alert_dd",
          severity: "CRITICAL",
          title: "Daily loss threshold approaching",
          source: "Risk Engine",
          createdAt: iso(-60),
          description: "Loss $412 vs $500 configured max. New entries auto-disabled.",
          suggestedAction: "Review open exposure. Consider controlled position reduction.",
          acknowledged: false,
        },
        ...alerts,
      ];
      break;
    case "executionUnknown":
      orders = [
        {
          id: "ord_01HXDRG6X",
          brokerTicket: null,
          clientRequestId: "req_1720706120_555",
          correlationId: "corr_unknown_777",
          symbol: "EURUSD",
          side: "BUY",
          type: "MARKET",
          volume: 0.5,
          requestedPrice: 1.086,
          filledPrice: null,
          stopLoss: 1.083,
          takeProfit: 1.09,
          slippage: null,
          strategy: "XDRG Trend Continuation",
          createdAt: iso(-45),
          updatedAt: iso(-20),
          status: "EXECUTION_UNKNOWN",
          rejectionReason: null,
          lifecycle: [
            { at: iso(-45), step: "CREATED", detail: "Signal accepted" },
            { at: iso(-44), step: "SUBMITTED", detail: "Sent to broker" },
            { at: iso(-20), step: "SYSTEM", detail: "Timeout waiting for acknowledgement (2000ms)" },
          ],
        },
        ...orders,
      ];
      alerts = [
        {
          id: "alert_unknown",
          severity: "CRITICAL",
          title: "Order execution status unknown",
          source: "Execution Engine",
          createdAt: iso(-18),
          description:
            "Order ord_01HXDRG6X timed out awaiting broker acknowledgement. Actual state at broker is uncertain.",
          suggestedAction: "DO NOT retry. Run reconciliation to determine final state.",
          acknowledged: false,
        },
        ...alerts,
      ];
      break;
  }

  return {
    positionsAvailable: true,
    positionsSourceFrameId: 1,
    positionsObservedAt: iso(-4),
    accountAvailable: true,
    accountSourceFrameId: 1,
    accountObservedAt: iso(-4),
    runtime,
    subsystems,
    broker,
    account: accountFor(scenario),
    strategies: STRATEGIES,
    positions: POSITIONS,
    orders,
    markets: MARKETS,
    alerts,
    incidents: INCIDENTS,
    riskLimits: RISK_LIMITS,
    breakers: BREAKERS,
    reconciliation,
    events: EVENTS,
    equityCurve: EQUITY,
  };
}

export const SCENARIOS: Array<{ key: ScenarioKey; label: string; description: string }> = [
  { key: "healthy", label: "Healthy", description: "Runtime READY. All subsystems OK." },
  { key: "degraded", label: "Degraded", description: "Broker latency elevated. Trading permitted." },
  { key: "brokerDown", label: "Broker Down", description: "Broker disconnected. Reconnecting." },
  { key: "reconciling", label: "Reconciling", description: "Rebuilding state from broker." },
  { key: "paused", label: "Paused", description: "Operator paused runtime." },
  { key: "killed", label: "Emergency Kill", description: "Runtime halted by operator." },
  { key: "drawdown", label: "Drawdown Warning", description: "Daily loss threshold approaching." },
  { key: "executionUnknown", label: "Execution Unknown", description: "Order timed out — broker state uncertain." },
];

// -----------------------------------------------------------------------------
// Trade Journal fixture. Sign convention enforced: netPnl === grossPnl + commission + swap.
// R-multiple deliberately null for a couple of rows to exercise the "n/a R"
// path in the journal summary.
// -----------------------------------------------------------------------------
function makeTrade(
  i: number,
  overrides: Partial<ClosedTrade> = {},
): ClosedTrade {
  const symbols = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "US500", "BTCUSD"] as const;
  const strategies = ["strat_trend", "strat_meanrev", "strat_breakout"] as const;
  const exitReasons: TradeExitReason[] = ["TP", "SL", "TRAIL", "PARTIAL_FINAL", "MANUAL"];
  const sym = symbols[i % symbols.length];
  const strat = strategies[i % strategies.length];
  const exit = exitReasons[i % exitReasons.length];
  // Deterministic pseudo-random outcome.
  const sign = i % 3 === 0 ? -1 : 1;
  const gross = sign * (18 + ((i * 7) % 90));
  const commission = -(0.8 + (i % 5) * 0.3); // always negative
  const swap = (i % 4 === 0 ? -1 : 1) * ((i % 3) * 0.4);
  const net = gross + commission + swap;
  const closedAtSec = -3600 * (i + 1);
  const holdSec = 300 + (i * 137) % 4200;
  // Deliberately null R on ~1 in 8 rows.
  const rNull = i % 8 === 7;
  const r = rNull ? null : sign * (0.2 + ((i % 10) * 0.28));
  return {
    tradeId: `trd_${(1000 + i).toString(36)}`,
    positionId: `pos_hist_${i}`,
    strategyId: strat,
    symbol: sym,
    direction: i % 2 === 0 ? "LONG" : "SHORT",
    entryPrice: 1000 + i,
    exitPrice: 1000 + i + sign,
    openedAt: iso(closedAtSec - holdSec),
    closedAt: iso(closedAtSec),
    holdingSeconds: holdSec,
    volumeInitial: 0.1 + ((i % 5) * 0.05),
    grossPnl: round2(gross),
    commission: round2(commission),
    swap: round2(swap),
    netPnl: round2(net),
    rMultiple: r === null ? null : round2(r),
    mfeR: r === null ? null : round2(Math.abs(r) + 0.15),
    maeR: r === null ? null : -round2(Math.abs(r) * 0.4),
    exitReason: exit,
    partialFills: [],
    tags: [],
    ...overrides,
  };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

const TRADE_HISTORY: ClosedTrade[] = Array.from({ length: 48 }, (_, i) => makeTrade(i));

/** Paged access for the fixture adapter. Deterministic ordering: newest first. */
export function getFixtureTradeHistory(cursor?: string | null, limit = 25) {
  const start = cursor ? Math.max(0, parseInt(cursor, 10) || 0) : 0;
  const end = Math.min(TRADE_HISTORY.length, start + limit);
  const trades = TRADE_HISTORY.slice(start, end);
  const nextCursor = end < TRADE_HISTORY.length ? String(end) : null;
  return { trades, nextCursor };
}

export function getAllFixtureTrades(): ClosedTrade[] {
  return TRADE_HISTORY;
}


/**
 * Empty snapshot for the LOCAL_RUNTIME data source when no runtime is connected.
 * Contains no fixture data — all lists are empty and the runtime is DISCONNECTED.
 * This is NOT a silent fallback: broker.tradingPermitted is false, all counters
 * are zero, and freshness is UNAVAILABLE. Consumers must render disconnected UI.
 */
export function createEmptySnapshot(): CockpitSnapshot {
  return {
    positionsAvailable: false,
    positionsSourceFrameId: null,
    positionsObservedAt: null,
    accountAvailable: false,
    accountSourceFrameId: null,
    accountObservedAt: null,
    runtime: {
      id: "rt_disconnected",
      sessionId: "",
      version: "",
      buildHash: "",
      environment: "LOCAL",
      tradingMode: "TRIAL",
      state: "DISCONNECTED",
      previousState: "DISCONNECTED",
      stateChangedAt: null,
      stateReason: "No local runtime connected.",
      startedAt: null,
      uptimeSec: null,
      lastHeartbeatAt: null,
      heartbeatLatencyMs: null,
      entriesEnabled: false,
      automationEnabled: false,
      hostname: "",
      os: "",
      pid: 0,
    },
    subsystems: [],
    broker: {
      broker: "—",
      server: "—",
      loginMasked: "—",
      accountMode: "TRIAL",
      connection: "DISCONNECTED",
      tradingPermitted: false,
      terminalVersion: "—",
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
  };
}
