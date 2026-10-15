export const API_URL = "http://127.0.0.1:8000";

export type BrokerStatus = "connected" | "disconnected" | "error" | "rate_limited";
export type FailureKind = "authentication" | "network" | "broker";

export type SystemStatus = {
  trading_mode: "paper";
  paper_only: true;
  allow_order_submission: false;
  initial_virtual_capital_usd: number;
  credentials_configured: boolean;
  broker_status: BrokerStatus;
  broker_message: string | null;
  failure_kind: FailureKind | null;
  alpaca_base_url: string;
  api_host: string;
  database_ok: boolean;
};

export type AccountSnapshot = {
  equity: string;
  buying_power: string;
  cash: string;
  currency: string;
  status: string;
};

export type BrokerAccount = {
  status: BrokerStatus;
  message: string | null;
  failure_kind: FailureKind | null;
  virtual_capital_usd: number;
  broker_equity_note: string;
  account: AccountSnapshot | null;
};

export type PositionSnapshot = {
  symbol: string;
  qty: string;
  side: string;
  market_value: string;
  avg_entry_price: string;
  unrealized_pl: string;
};

export type BrokerPositions = {
  status: BrokerStatus;
  message: string | null;
  failure_kind: FailureKind | null;
  positions: PositionSnapshot[];
};

export type SymbolCoverage = {
  symbol: string;
  feed: string;
  bar_count: number;
  earliest_session: string | null;
  latest_session: string | null;
  gap_count: number;
  missing_start: number;
  missing_middle: number;
  missing_end: number;
};

export type AuditEvent = {
  id: number;
  created_at: string;
  event_type: string;
  event_level: string;
  component: string;
  status: string;
  title: string;
  summary: string;
  correlation_id: string;
  run_id: number | null;
  payload: Record<string, unknown>;
  error_code: string | null;
  error_message_safe: string | null;
};

export type AuditRun = {
  id: number;
  created_at: string;
  finished_at: string | null;
  run_type: string;
  component: string;
  status: string;
  title: string;
  summary: string;
  correlation_id: string;
  payload: Record<string, unknown>;
  error_code: string | null;
  error_message_safe: string | null;
};

export type DecisionTrace = {
  id: number;
  created_at: string;
  source_type: string;
  symbols: string[];
  decision_action: string;
  proposed_notional: string | null;
  decision_status: string;
  rationale_summary: string;
  evidence_summary: string;
  warnings: string;
  market_data_snapshot: string;
  research_note_ids: string;
  backtest_id: string | null;
  risk_decision_id: string | null;
  broker_event_id: string | null;
  model_provider: string | null;
  confidence: string | null;
  explanation: Record<string, unknown>;
};

export type ObservabilityOverview = {
  event_count: number;
  warning_count: number;
  error_count: number;
  run_count: number;
  decision_trace_count: number;
  recent_events: AuditEvent[];
};

export type SystemHealth = {
  api_ok: boolean;
  trading_mode: "paper";
  allow_order_submission: false;
  api_host: string;
  alpaca_base_url: string;
  operational_database_ok: boolean;
  market_data_database_present: boolean;
  broker_status: BrokerStatus;
  broker_message: string | null;
  last_event_at: string | null;
  event_count: number;
  run_count: number;
  decision_trace_count: number;
};

export type MarketDataStatus = {
  symbols: string[];
  feeds: string[];
  earliest_session: string | null;
  latest_session: string | null;
  bar_count: number;
  requested_start: string | null;
  requested_end: string | null;
  requested_feed: string | null;
  coverage: SymbolCoverage[];
  last_successful_ingestion: string | null;
  warnings: string[];
  coverage_complete: boolean;
  suitable_for_research: boolean;
  caveat: string;
};

const BROKER_STATUSES: readonly BrokerStatus[] = [
  "connected",
  "disconnected",
  "error",
  "rate_limited",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readStatus(value: unknown): BrokerStatus {
  if (typeof value === "string" && BROKER_STATUSES.includes(value as BrokerStatus)) {
    return value as BrokerStatus;
  }
  throw new Error("Unexpected broker status");
}

function readFailureKind(value: unknown): FailureKind | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (value === "authentication" || value === "network" || value === "broker") {
    return value;
  }
  throw new Error("Unexpected failure kind");
}

function readMessage(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string") {
    return value;
  }
  throw new Error("Unexpected message");
}

function readAccountSnapshot(value: unknown): AccountSnapshot | null {
  if (value === null) {
    return null;
  }
  if (!isRecord(value)) {
    throw new Error("Unexpected account");
  }
  const fields = ["equity", "buying_power", "cash", "currency", "status"] as const;
  const snapshot = {} as AccountSnapshot;
  for (const field of fields) {
    if (typeof value[field] !== "string") {
      throw new Error("Unexpected account field");
    }
    snapshot[field] = value[field];
  }
  return snapshot;
}

export function parseSystemStatus(value: unknown): SystemStatus {
  if (!isRecord(value)) {
    throw new Error("Unexpected status payload");
  }
  if (value.trading_mode !== "paper" || value.paper_only !== true) {
    throw new Error("API is not reporting paper-only mode");
  }
  if (value.allow_order_submission !== false) {
    throw new Error("API is reporting order submission as enabled");
  }
  if (typeof value.initial_virtual_capital_usd !== "number") {
    throw new Error("Unexpected virtual capital");
  }
  if (typeof value.credentials_configured !== "boolean" || typeof value.database_ok !== "boolean") {
    throw new Error("Unexpected system flags");
  }
  if (value.alpaca_base_url !== "https://paper-api.alpaca.markets") {
    throw new Error("API is not locked to the Alpaca paper host");
  }
  if (value.api_host !== "127.0.0.1") {
    throw new Error("API is not bound to localhost");
  }
  return {
    trading_mode: "paper",
    paper_only: true,
    allow_order_submission: false,
    initial_virtual_capital_usd: value.initial_virtual_capital_usd,
    credentials_configured: value.credentials_configured,
    broker_status: readStatus(value.broker_status),
    broker_message: readMessage(value.broker_message),
    failure_kind: readFailureKind(value.failure_kind),
    alpaca_base_url: value.alpaca_base_url,
    api_host: value.api_host,
    database_ok: value.database_ok,
  };
}

export function parseBrokerAccount(value: unknown): BrokerAccount {
  if (!isRecord(value)) {
    throw new Error("Unexpected account payload");
  }
  if (typeof value.virtual_capital_usd !== "number" || typeof value.broker_equity_note !== "string") {
    throw new Error("Unexpected account envelope");
  }
  return {
    status: readStatus(value.status),
    message: readMessage(value.message),
    failure_kind: readFailureKind(value.failure_kind),
    virtual_capital_usd: value.virtual_capital_usd,
    broker_equity_note: value.broker_equity_note,
    account: readAccountSnapshot(value.account),
  };
}

export function parsePositions(value: unknown): BrokerPositions {
  if (!isRecord(value) || !Array.isArray(value.positions)) {
    throw new Error("Unexpected positions payload");
  }
  const positions = value.positions.map((item) => {
    if (!isRecord(item)) {
      throw new Error("Unexpected position");
    }
    const fields = ["symbol", "qty", "side", "market_value", "avg_entry_price", "unrealized_pl"] as const;
    const position = {} as PositionSnapshot;
    for (const field of fields) {
      if (typeof item[field] !== "string") {
        throw new Error("Unexpected position field");
      }
      position[field] = item[field];
    }
    return position;
  });
  return {
    status: readStatus(value.status),
    message: readMessage(value.message),
    failure_kind: readFailureKind(value.failure_kind),
    positions,
  };
}

async function readJson(path: string): Promise<unknown> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API request failed (${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

function readStringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Unexpected ${label}`);
  }
  return value;
}

export function parseMarketDataStatus(value: unknown): MarketDataStatus {
  if (!isRecord(value)) {
    throw new Error("Unexpected market data payload");
  }
  if (!Array.isArray(value.coverage)) {
    throw new Error("Unexpected market data coverage");
  }
  const coverage = value.coverage.map((item) => {
    if (!isRecord(item)) {
      throw new Error("Unexpected coverage row");
    }
    if (
      typeof item.symbol !== "string" ||
      typeof item.feed !== "string" ||
      typeof item.bar_count !== "number" ||
      typeof item.gap_count !== "number" ||
      typeof item.missing_start !== "number" ||
      typeof item.missing_middle !== "number" ||
      typeof item.missing_end !== "number" ||
      !isOptionalString(item.earliest_session) ||
      !isOptionalString(item.latest_session)
    ) {
      throw new Error("Unexpected coverage field");
    }
    return {
      symbol: item.symbol,
      feed: item.feed,
      bar_count: item.bar_count,
      earliest_session: item.earliest_session,
      latest_session: item.latest_session,
      gap_count: item.gap_count,
      missing_start: item.missing_start,
      missing_middle: item.missing_middle,
      missing_end: item.missing_end,
    };
  });
  if (
    typeof value.bar_count !== "number" ||
    typeof value.coverage_complete !== "boolean" ||
    typeof value.suitable_for_research !== "boolean" ||
    typeof value.caveat !== "string" ||
    !isOptionalString(value.requested_start) ||
    !isOptionalString(value.requested_end) ||
    !isOptionalString(value.requested_feed)
  ) {
    throw new Error("Unexpected market data summary");
  }
  const earliest = value.earliest_session;
  const latest = value.latest_session;
  const last = value.last_successful_ingestion;
  if (
    !isOptionalString(earliest) ||
    !isOptionalString(latest) ||
    !isOptionalString(last)
  ) {
    throw new Error("Unexpected market data dates");
  }
  return {
    symbols: readStringList(value.symbols, "symbols"),
    feeds: readStringList(value.feeds, "feeds"),
    earliest_session: earliest,
    latest_session: latest,
    bar_count: value.bar_count,
    requested_start: value.requested_start,
    requested_end: value.requested_end,
    requested_feed: value.requested_feed,
    coverage,
    last_successful_ingestion: last,
    warnings: readStringList(value.warnings, "warnings"),
    coverage_complete: value.coverage_complete,
    suitable_for_research: value.suitable_for_research,
    caveat: value.caveat,
  };
}

function isOptionalString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export async function loadMarketData(): Promise<MarketDataStatus> {
  return parseMarketDataStatus(await readJson("/api/market-data/status"));
}

function readOptionalString(value: unknown, label: string): string | null {
  if (!isOptionalString(value)) {
    throw new Error(`Unexpected ${label}`);
  }
  return value;
}

function readPayload(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error("Unexpected payload");
  }
  return value;
}

function parseEvent(value: unknown): AuditEvent {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.summary !== "string") {
    throw new Error("Unexpected event");
  }
  if (
    typeof value.created_at !== "string" ||
    typeof value.event_type !== "string" ||
    typeof value.event_level !== "string" ||
    typeof value.component !== "string" ||
    typeof value.status !== "string" ||
    typeof value.title !== "string" ||
    typeof value.correlation_id !== "string"
  ) {
    throw new Error("Unexpected event field");
  }
  return {
    id: value.id,
    created_at: value.created_at,
    event_type: value.event_type,
    event_level: value.event_level,
    component: value.component,
    status: value.status,
    title: value.title,
    summary: value.summary,
    correlation_id: value.correlation_id,
    run_id: typeof value.run_id === "number" ? value.run_id : null,
    payload: readPayload(value.payload),
    error_code: readOptionalString(value.error_code, "error code"),
    error_message_safe: readOptionalString(value.error_message_safe, "safe error"),
  };
}

function parseRun(value: unknown): AuditRun {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.summary !== "string") {
    throw new Error("Unexpected run");
  }
  if (
    typeof value.created_at !== "string" ||
    typeof value.run_type !== "string" ||
    typeof value.component !== "string" ||
    typeof value.status !== "string" ||
    typeof value.title !== "string" ||
    typeof value.correlation_id !== "string"
  ) {
    throw new Error("Unexpected run field");
  }
  return {
    id: value.id,
    created_at: value.created_at,
    finished_at: readOptionalString(value.finished_at, "finished at"),
    run_type: value.run_type,
    component: value.component,
    status: value.status,
    title: value.title,
    summary: value.summary,
    correlation_id: value.correlation_id,
    payload: readPayload(value.payload),
    error_code: readOptionalString(value.error_code, "error code"),
    error_message_safe: readOptionalString(value.error_message_safe, "safe error"),
  };
}

export function parseObservabilityOverview(value: unknown): ObservabilityOverview {
  if (!isRecord(value) || !Array.isArray(value.recent_events)) {
    throw new Error("Unexpected observability overview");
  }
  return {
    event_count: readCount(value.event_count),
    warning_count: readCount(value.warning_count),
    error_count: readCount(value.error_count),
    run_count: readCount(value.run_count),
    decision_trace_count: readCount(value.decision_trace_count),
    recent_events: value.recent_events.map(parseEvent),
  };
}

function readCount(value: unknown): number {
  if (typeof value !== "number") {
    throw new Error("Unexpected observability count");
  }
  return value;
}

export function parseEventPage(value: unknown): { items: AuditEvent[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected event page");
  }
  return { items: value.items.map(parseEvent), total: value.total };
}

export function parseRunPage(value: unknown): { items: AuditRun[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected run page");
  }
  return { items: value.items.map(parseRun), total: value.total };
}

function parseDecision(value: unknown): DecisionTrace {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.rationale_summary !== "string") {
    throw new Error("Unexpected decision trace");
  }
  if (
    typeof value.created_at !== "string" ||
    typeof value.source_type !== "string" ||
    typeof value.decision_action !== "string" ||
    typeof value.decision_status !== "string" ||
    typeof value.evidence_summary !== "string" ||
    typeof value.warnings !== "string" ||
    typeof value.market_data_snapshot !== "string" ||
    typeof value.research_note_ids !== "string" ||
    !Array.isArray(value.symbols) ||
    value.symbols.some((item) => typeof item !== "string")
  ) {
    throw new Error("Unexpected decision field");
  }
  const symbols = value.symbols.filter((item): item is string => typeof item === "string");
  return {
    id: value.id,
    created_at: value.created_at,
    source_type: value.source_type,
    symbols,
    decision_action: value.decision_action,
    proposed_notional: readOptionalString(value.proposed_notional, "notional"),
    decision_status: value.decision_status,
    rationale_summary: value.rationale_summary,
    evidence_summary: value.evidence_summary,
    warnings: value.warnings,
    market_data_snapshot: value.market_data_snapshot,
    research_note_ids: value.research_note_ids,
    backtest_id: readOptionalString(value.backtest_id, "backtest"),
    risk_decision_id: readOptionalString(value.risk_decision_id, "risk decision"),
    broker_event_id: readOptionalString(value.broker_event_id, "broker event"),
    model_provider: readOptionalString(value.model_provider, "model"),
    confidence: readOptionalString(value.confidence, "confidence"),
    explanation: readPayload(value.explanation),
  };
}

export function parseDecisionPage(value: unknown): { items: DecisionTrace[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected decision page");
  }
  return { items: value.items.map(parseDecision), total: value.total };
}

export function parseSystemHealth(value: unknown): SystemHealth {
  if (!isRecord(value)) {
    throw new Error("Unexpected health payload");
  }
  if (value.trading_mode !== "paper" || value.allow_order_submission !== false || value.api_ok !== true) {
    throw new Error("API is not reporting a paper-only health check");
  }
  if (value.alpaca_base_url !== "https://paper-api.alpaca.markets" || value.api_host !== "127.0.0.1") {
    throw new Error("API host lock is not intact");
  }
  if (
    typeof value.operational_database_ok !== "boolean" ||
    typeof value.market_data_database_present !== "boolean" ||
    typeof value.event_count !== "number" ||
    typeof value.run_count !== "number" ||
    typeof value.decision_trace_count !== "number"
  ) {
    throw new Error("Unexpected health fields");
  }
  return {
    api_ok: true,
    trading_mode: "paper",
    allow_order_submission: false,
    api_host: value.api_host,
    alpaca_base_url: value.alpaca_base_url,
    operational_database_ok: value.operational_database_ok,
    market_data_database_present: value.market_data_database_present,
    broker_status: readStatus(value.broker_status),
    broker_message: readMessage(value.broker_message),
    last_event_at: readOptionalString(value.last_event_at, "last event"),
    event_count: value.event_count,
    run_count: value.run_count,
    decision_trace_count: value.decision_trace_count,
  };
}

export async function loadObservability(): Promise<ObservabilityOverview> {
  return parseObservabilityOverview(await readJson("/api/observability/overview"));
}

export async function loadEvents(query: string): Promise<{ items: AuditEvent[]; total: number }> {
  return parseEventPage(await readJson(`/api/observability/events${query}`));
}

export async function loadEvent(id: number): Promise<AuditEvent> {
  return parseEvent(await readJson(`/api/observability/events/${id}`));
}

export async function loadRuns(): Promise<{ items: AuditRun[]; total: number }> {
  return parseRunPage(await readJson("/api/observability/runs"));
}

export async function loadRun(id: number): Promise<AuditRun> {
  return parseRun(await readJson(`/api/observability/runs/${id}`));
}

export async function loadDecisions(): Promise<{ items: DecisionTrace[]; total: number }> {
  return parseDecisionPage(await readJson("/api/observability/decision-traces"));
}

export async function loadHealth(): Promise<SystemHealth> {
  return parseSystemHealth(await readJson("/api/observability/system-health"));
}

export async function loadOverview(): Promise<{
  status: SystemStatus;
  account: BrokerAccount;
  positions: BrokerPositions;
}> {
  const [status, account, positions] = await Promise.all([
    readJson("/api/system/status"),
    readJson("/api/broker/account"),
    readJson("/api/broker/positions"),
  ]);
  return {
    status: parseSystemStatus(status),
    account: parseBrokerAccount(account),
    positions: parsePositions(positions),
  };
}

export function formatUsd(value: number | string): string {
  const amount = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(amount)) {
    return String(value);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}
