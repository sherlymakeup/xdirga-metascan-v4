// XDIRGA METASCAN — frontend data contracts.
// These mirror the eventual local runtime + broker + MT5 gateway responses.

export type RuntimeState =
  | "DISCONNECTED"
  | "INITIALIZING"
  | "DEGRADED"
  | "RECONNECTING"
  | "RECONCILING"
  | "READY"
  | "PAUSED"
  | "STOPPING"
  | "STOPPED"
  | "ERROR"
  | "KILLED";

/**
 * Broker account environment. `PAPER` was intentionally removed from the
 * product domain — fixtures use the runtime-level `FrontendDataSource`,
 * not a fake paper-trading mode.
 * @deprecated Prefer `BrokerEnvironment` from `@/lib/runtime/runtime-types`.
 */
export type TradingMode = "TRIAL" | "LIVE";

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type LogSeverity = "TRACE" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export type ConnectionState =
  | "CONNECTED"
  | "DISCONNECTED"
  | "RECONNECTING"
  | "DEGRADED"
  | "UNKNOWN";

export type DataFreshness = "FRESH" | "DELAYED" | "STALE" | "UNAVAILABLE";

export interface RuntimeStatus {
  id: string;
  sessionId: string;
  version: string;
  buildHash: string;
  environment: "LOCAL";
  tradingMode: TradingMode;
  state: RuntimeState;
  previousState: RuntimeState;
  stateChangedAt: string;
  stateReason: string;
  startedAt: string;
  uptimeSec: number;
  lastHeartbeatAt: string;
  heartbeatLatencyMs: number;
  entriesEnabled: boolean;
  automationEnabled: boolean;
  hostname: string;
  os: string;
  pid: number;
}

export interface SubsystemHealth {
  key: string;
  label: string;
  state: "OK" | "DEGRADED" | "DOWN" | "UNKNOWN";
  lastHeartbeatAt: string;
  latencyMs: number | null;
  restartCount: number;
  currentAction: string | null;
  lastError: string | null;
}

export interface BrokerStatus {
  broker: string;
  server: string;
  loginMasked: string;
  accountMode: TradingMode;
  connection: ConnectionState;
  tradingPermitted: boolean;
  terminalVersion: string;
  lastTickAt: string;
  lastRequestAt: string;
  queueDepth: number;
  avgLatencyMs: number;
  timeoutCount: number;
  reconnectAttempts: number;
}

export interface AccountSnapshot {
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  marginLevel: number;
  floatingPnl: number;
  realizedPnlToday: number;
  realizedPnlWeek: number;
  dailyDrawdown: number;
  maxDrawdown: number;
  grossExposure: number;
  netExposure: number;
  openPositions: number;
  pendingOrders: number;
  tradesToday: number;
  winRate: number;
  profitFactor: number;
  riskUtilization: number;
  updatedAt: string;
  freshness: DataFreshness;
}

export type OrderSide = "BUY" | "SELL";
export type OrderType = "MARKET" | "LIMIT" | "STOP" | "STOP_LIMIT";
export type OrderStatus =
  | "CREATED"
  | "VALIDATED"
  | "RISK_CHECKED"
  | "SAFETY_CHECKED"
  | "SUBMITTED"
  | "ACKNOWLEDGED"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "TIMED_OUT"
  | "EXECUTION_UNKNOWN"
  | "RECONCILED";

export interface OrderLifecycleEvent {
  at: string;
  step: OrderStatus | "BROKER_ACK" | "OPERATOR" | "SYSTEM";
  detail: string;
  latencyMs?: number;
}

export interface Order {
  id: string;
  brokerTicket: string | null;
  clientRequestId: string;
  correlationId: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  volume: number;
  requestedPrice: number | null;
  filledPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  slippage: number | null;
  strategy: string;
  createdAt: string;
  updatedAt: string;
  status: OrderStatus;
  rejectionReason: string | null;
  lifecycle: OrderLifecycleEvent[];
}

export type PositionProtection =
  | "PROTECTED"
  | "PARTIALLY_PROTECTED"
  | "UNPROTECTED"
  | "INVALID_PROTECTION"
  | "UNKNOWN";

export type PositionState = "OPEN" | "CLOSING" | "CLOSED" | "RECONCILE_REQUIRED";

// -----------------------------------------------------------------------------
// Position Autopilot Management (Phase 5F.5)
// -----------------------------------------------------------------------------

export type PositionManagementSource = "STRATEGY" | "MANUAL_OVERRIDE";

export type BreakEvenState = "PENDING" | "APPLIED" | "SKIPPED";

export interface BreakEvenPlan {
  enabled: boolean;
  /** R-multiple at which break-even arms (e.g. 1.0 = at 1R profit). */
  triggerR: number;
  /** Buffer beyond entry (in symbol points) to cover commission + swap. */
  offsetPoints: number;
  state: BreakEvenState;
  appliedAt: string | null;
}

export type TrailingMode = "OFF" | "FIXED_POINTS" | "ATR" | "STEP" | "STRUCTURE";

export interface TrailingPlan {
  mode: TrailingMode;
  active: boolean;
  distancePoints: number | null;
  currentStopPrice: number | null;
  lastMovedAt: string | null;
  moveCount: number;
}

export type PartialTpLevelState = "PENDING" | "EXECUTED" | "SKIPPED" | "FAILED";

export interface PartialTpLevel {
  levelId: string;
  /** Trigger in R-multiple. */
  atR: number;
  /** Percent of ORIGINAL position volume to close at this level. */
  closePercent: number;
  state: PartialTpLevelState;
  executedAt: string | null;
  executedPrice: number | null;
  closedVolume: number | null;
}

export interface PartialTpPlan {
  levels: PartialTpLevel[];
}

export type TimeExitState = "PENDING" | "EXECUTED" | "DISABLED";

export interface TimeExitPlan {
  maxHoldUntil: string | null;
  state: TimeExitState;
}

export interface PositionManagement {
  /** Identifies the active management plan revision. */
  planId: string;
  source: PositionManagementSource;
  breakEven: BreakEvenPlan;
  trailing: TrailingPlan;
  partialTp: PartialTpPlan;
  timeExit: TimeExitPlan;
  /** Human-readable next planned action, e.g. "Trail SL to 2345.10 when bid > 2350.00". */
  nextAction: string | null;
  lastError: string | null;
  /** Operator-controlled pause on autopilot for this position only. */
  paused: boolean;
}

export interface Position {
  id: string;
  brokerTicket: string;
  ownership: "BOT_MANAGED" | "FOREIGN" | "UNKNOWN";
  symbol: string;
  side: OrderSide;
  volume: number;
  entryPrice: number;
  currentPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
  floatingPnl: number;
  realizedPnl: number | null;
  riskAmount: number | null;
  riskPct: number | null;
  openedAt: string | null;
  strategy: string | null;
  protection: PositionProtection;
  state: PositionState;
  rMultiple: number | null;
  mfe: number | null;
  mae: number | null;

  // -------- Sign convention --------
  // commission and swap are SIGNED values exactly as reported by MT5.
  // Broker costs (commission, negative swap) are NEGATIVE numbers; broker
  // credits are POSITIVE. The identity below MUST hold on every position
  // and every ClosedTrade:
  //
  //     netPnl = floatingPnl + commission + swap    (open positions)
  //     netPnl = grossPnl    + commission + swap    (closed trades)
  //
  // Do NOT subtract commission/swap. See HANDOFF.md §"Sign convention".
  commission: number;
  swap: number;
  netPnl: number;

  /** Active autopilot management plan. Null when strategy is not managing this position. */
  management: PositionManagement | null;
}

export type StrategyStatus =
  | "DISABLED"
  | "IDLE"
  | "WARMING_UP"
  | "ACTIVE"
  | "PAUSED"
  | "BLOCKED"
  | "DEGRADED"
  | "ERROR";

export interface Strategy {
  id: string;
  name: string;
  version: string;
  symbols: string[];
  timeframe: string;
  status: StrategyStatus;
  tradingMode: TradingMode;
  entriesEnabled: boolean;
  allocationPct: number;
  pnlToday: number;
  drawdown: number;
  signalsToday: number;
  lastSignalAt: string | null;
  lastExecutionAt: string | null;
  currentBias: "LONG" | "SHORT" | "FLAT";
  confidence: number;
  openPositions: number;
  health: "OK" | "DEGRADED" | "ERROR";
}

export interface MarketSymbol {
  symbol: string;
  group: "FX" | "METALS" | "INDICES" | "CRYPTO" | null;
  bid: number;
  ask: number;
  spread: number;
  last: number;
  changePct: number | null;
  sessionOpen: boolean | null;
  tradingPermitted: boolean;
  tickAgeMs: number;
  freshness: DataFreshness;
  contractSize: number;
  tickSize: number;
  minVolume: number;
  maxVolume: number;
  volumeStep: number;
  swapLong: number | null;
  swapShort: number | null;
  marginRequirement: number | null;
}

export interface RiskLimit {
  key: string;
  label: string;
  configured: number;
  current: number;
  unit: "PCT" | "USD" | "COUNT" | "MS" | "PRICE";
  warnAt: number;
  breachAt: number;
  breached: boolean;
  changedAt: string;
  changedBy: string;
}

export type BreakerState = "CLOSED" | "WARNING" | "OPEN" | "RECOVERING" | "MANUAL_LOCK";

export interface CircuitBreaker {
  key: string;
  label: string;
  state: BreakerState;
  triggerCondition: string;
  currentValue: string;
  threshold: string;
  triggeredAt: string | null;
  recoveryCondition: string;
  manualResetAllowed: boolean;
  lastResetAt: string | null;
}

export interface Alert {
  id: string;
  severity: Severity;
  title: string;
  source: string;
  createdAt: string;
  description: string;
  suggestedAction: string;
  acknowledged: boolean;
  incidentId?: string;
}

export type IncidentStatus =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "INVESTIGATING"
  | "MITIGATED"
  | "RESOLVED";

export interface Incident {
  id: string;
  severity: Severity;
  status: IncidentStatus;
  title: string;
  startedAt: string;
  durationSec: number;
  source: string;
  impact: string;
  affectedComponents: string[];
  rootCause: string | null;
  resolution: string | null;
}

export interface ReconciliationIssue {
  entity: "ORDER" | "POSITION";
  entityId: string;
  runtimeState: string;
  brokerState: string;
  difference: string;
  severity: Severity;
  suggestedAction: string;
  resolved: boolean;
}

export interface ReconciliationSummary {
  state: "IDLE" | "RUNNING" | "OK" | "ISSUES" | "FAILED";
  lastRunAt: string;
  brokerOrders: number;
  runtimeOrders: number;
  brokerPositions: number;
  runtimePositions: number;
  missingOrders: number;
  unknownOrders: number;
  positionMismatches: number;
  volumeMismatches: number;
  stateMismatches: number;
  issues: ReconciliationIssue[];
}

export interface RuntimeEvent {
  id: string;
  at: string;
  severity: LogSeverity;
  source: string;
  component: string;
  message: string;
  correlationId?: string;
  orderId?: string;
  positionId?: string;
  strategy?: string;
  symbol?: string;
  payload?: Record<string, unknown>;
}

export interface EquityPoint {
  at: string;
  equity: number;
  balance: number;
  floatingPnl: number;
  drawdown: number;
}

// -----------------------------------------------------------------------------
// Trade Journal (Phase 5F.5)
// -----------------------------------------------------------------------------

export type TradeDirection = "LONG" | "SHORT";

export type TradeExitReason =
  | "TP"
  | "SL"
  | "TRAIL"
  | "PARTIAL_FINAL"
  | "MANUAL"
  | "TIME_EXIT"
  | "KILL_SWITCH"
  | "BREAKER"
  | "OTHER";

export interface ClosedTradePartialFill {
  closedAt: string;
  price: number;
  volume: number;
  /** Signed. Same convention as ClosedTrade.netPnl. */
  netPnl: number;
}

export interface ClosedTrade {
  tradeId: string;
  positionId: string;
  strategyId: string;
  symbol: string;
  direction: TradeDirection;
  entryPrice: number;
  exitPrice: number;
  openedAt: string;
  closedAt: string;
  holdingSeconds: number;
  volumeInitial: number;

  /** Gross PnL before commission/swap. Signed. */
  grossPnl: number;
  /** Signed as reported by MT5. Costs are NEGATIVE. */
  commission: number;
  /** Signed as reported by MT5. Costs are NEGATIVE. */
  swap: number;
  /** Identity: netPnl === grossPnl + commission + swap (addition, not subtraction). */
  netPnl: number;

  /** R-multiple. Null when the trade was opened without a valid initial risk. */
  rMultiple: number | null;
  /** Max Favourable Excursion in R-multiples. Null when unknown. */
  mfeR: number | null;
  /** Max Adverse Excursion in R-multiples. Null when unknown. */
  maeR: number | null;

  exitReason: TradeExitReason;
  partialFills: ClosedTradePartialFill[];
  tags: string[];
}

export interface TradeHistoryPage {
  trades: ClosedTrade[];
  nextCursor: string | null;
}

export interface TradeHistoryQuery {
  cursor?: string | null;
  limit?: number;
}

export type ScenarioKey =
  | "healthy"
  | "degraded"
  | "brokerDown"
  | "reconciling"
  | "paused"
  | "killed"
  | "drawdown"
  | "executionUnknown";

export interface CockpitSnapshot {
  runtime: RuntimeStatus;
  subsystems: SubsystemHealth[];
  broker: BrokerStatus;
  account: AccountSnapshot;
  strategies: Strategy[];
  positions: Position[];
  orders: Order[];
  markets: MarketSymbol[];
  alerts: Alert[];
  incidents: Incident[];
  riskLimits: RiskLimit[];
  breakers: CircuitBreaker[];
  reconciliation: ReconciliationSummary;
  events: RuntimeEvent[];
  equityCurve: EquityPoint[];
}
