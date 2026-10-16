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

export type EventHistogramBucket = {
  t: string;
  count: number;
  errors: number;
  warnings: number;
};

export type EventHistogram = {
  bucket: string;
  buckets: EventHistogramBucket[];
};

export function parseEventHistogram(value: unknown): EventHistogram {
  if (!isRecord(value) || typeof value.bucket !== "string" || !Array.isArray(value.buckets)) {
    throw new Error("Unexpected event histogram");
  }
  return {
    bucket: value.bucket,
    buckets: value.buckets.map((item) => {
      if (
        !isRecord(item) ||
        typeof item.t !== "string" ||
        typeof item.count !== "number" ||
        typeof item.errors !== "number" ||
        typeof item.warnings !== "number"
      ) {
        throw new Error("Unexpected histogram bucket");
      }
      return {
        t: item.t,
        count: item.count,
        errors: item.errors,
        warnings: item.warnings,
      };
    }),
  };
}

export async function loadEventHistogram(query: string): Promise<EventHistogram> {
  return parseEventHistogram(await readJson(`/api/observability/events/histogram${query}`));
}

export type MarketBar = {
  symbol: string;
  session_date: string;
  bar_timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  provider: string;
  feed: string;
  adjustment: string;
  timeframe: string;
  currency: string;
  available_at: string;
  first_retrieved_at: string;
  content_hash: string;
};

export type MarketBarPage = {
  items: MarketBar[];
  total: number;
  limit: number;
  offset: number;
  symbol: string;
  feed: string;
  provider: string;
  adjustment: string;
  timeframe: string;
  start: string;
  end: string;
  caveat: string;
};

export function parseMarketBarPage(value: unknown): MarketBarPage {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected market bars page");
  }
  if (
    typeof value.symbol !== "string" ||
    typeof value.feed !== "string" ||
    typeof value.provider !== "string" ||
    typeof value.adjustment !== "string" ||
    typeof value.timeframe !== "string" ||
    typeof value.start !== "string" ||
    typeof value.end !== "string" ||
    typeof value.caveat !== "string" ||
    typeof value.limit !== "number" ||
    typeof value.offset !== "number"
  ) {
    throw new Error("Unexpected market bars metadata");
  }
  const items = value.items.map((item) => {
    if (!isRecord(item)) {
      throw new Error("Unexpected market bar");
    }
    const fields = [
      "symbol",
      "session_date",
      "bar_timestamp",
      "open",
      "high",
      "low",
      "close",
      "volume",
      "provider",
      "feed",
      "adjustment",
      "timeframe",
      "currency",
      "available_at",
      "first_retrieved_at",
      "content_hash",
    ] as const;
    const bar = {} as MarketBar;
    for (const field of fields) {
      if (typeof item[field] !== "string") {
        throw new Error(`Unexpected market bar field ${field}`);
      }
      bar[field] = item[field];
    }
    return bar;
  });
  return {
    items,
    total: value.total,
    limit: value.limit,
    offset: value.offset,
    symbol: value.symbol,
    feed: value.feed,
    provider: value.provider,
    adjustment: value.adjustment,
    timeframe: value.timeframe,
    start: value.start,
    end: value.end,
    caveat: value.caveat,
  };
}

export async function loadMarketBars(params: {
  symbol: string;
  feed?: string;
  start: string;
  end: string;
  limit?: number;
  offset?: number;
}): Promise<MarketBarPage> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    feed: params.feed ?? "sip",
    start: params.start,
    end: params.end,
  });
  if (params.limit !== undefined) {
    query.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    query.set("offset", String(params.offset));
  }
  return parseMarketBarPage(await readJson(`/api/market-data/bars?${query.toString()}`));
}

/** Page through the chart API until every bar in the window is loaded. */
export async function loadAllMarketBars(params: {
  symbol: string;
  feed?: string;
  start: string;
  end: string;
  pageSize?: number;
}): Promise<MarketBarPage & { complete: boolean; pages: number }> {
  const pageSize = params.pageSize ?? 5000;
  const first = await loadMarketBars({
    ...params,
    limit: pageSize,
    offset: 0,
  });
  const items = [...first.items];
  let offset = first.items.length;
  let pages = 1;
  while (items.length < first.total) {
    const page = await loadMarketBars({
      ...params,
      limit: pageSize,
      offset,
    });
    if (page.items.length === 0) {
      break;
    }
    items.push(...page.items);
    offset += page.items.length;
    pages += 1;
    if (pages > 20) {
      break;
    }
  }
  return {
    ...first,
    items,
    limit: items.length,
    offset: 0,
    complete: items.length === first.total,
    pages,
  };
}

export type ResearchVerifyCheck = {
  name: string;
  verdict: string;
  detail: string;
};

export type ResearchVerify = {
  run_id: number;
  verdict: string;
  checks: ResearchVerifyCheck[];
  label: string;
  is_statistical_claim: false;
  is_broker_execution: false;
};

export function parseResearchVerify(value: unknown): ResearchVerify {
  if (!isRecord(value) || typeof value.run_id !== "number" || typeof value.verdict !== "string") {
    throw new Error("Unexpected verify payload");
  }
  if (
    typeof value.label !== "string" ||
    value.is_statistical_claim !== false ||
    value.is_broker_execution !== false ||
    !Array.isArray(value.checks)
  ) {
    throw new Error("Unexpected verify fields");
  }
  return {
    run_id: value.run_id,
    verdict: value.verdict,
    label: value.label,
    is_statistical_claim: false,
    is_broker_execution: false,
    checks: value.checks.map((item) => {
      if (
        !isRecord(item) ||
        typeof item.name !== "string" ||
        typeof item.verdict !== "string" ||
        typeof item.detail !== "string"
      ) {
        throw new Error("Unexpected verify check");
      }
      return { name: item.name, verdict: item.verdict, detail: item.detail };
    }),
  };
}

export async function loadResearchRunVerify(id: number): Promise<ResearchVerify> {
  return parseResearchVerify(await readJson(`/api/research/runs/${id}/verify`));
}

export async function loadEvent(id: number): Promise<AuditEvent> {
  return parseEvent(await readJson(`/api/observability/events/${id}`));
}

export async function loadRuns(query = ""): Promise<{ items: AuditRun[]; total: number }> {
  return parseRunPage(await readJson(`/api/observability/runs${query}`));
}

export async function loadRun(id: number): Promise<AuditRun> {
  return parseRun(await readJson(`/api/observability/runs/${id}`));
}

export async function loadDecisions(
  query = "",
): Promise<{ items: DecisionTrace[]; total: number }> {
  return parseDecisionPage(await readJson(`/api/observability/decision-traces${query}`));
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

export type ResearchExperiment = {
  experiment_id: string;
  hypothesis_id: string;
  title: string;
  description: string;
  citations: string[];
  created_at: string;
  config: Record<string, unknown>;
};

export type ResearchRun = {
  id: number;
  experiment_id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  git_commit: string | null;
  engine_version: string;
  dataset_fingerprint: string;
  outcome_summary: string;
  caveats: string[];
  label: string;
  is_paper_trading: boolean;
  is_broker_execution: boolean;
  config: Record<string, unknown>;
  audit_run_id: number | null;
  error_code: string;
  error_message_safe: string;
};

export type ResearchRunDetail = ResearchRun & {
  metrics: ResearchMetric[];
  research_mode: string;
};

export type ResearchMetric = {
  strategy_id: string;
  window: string;
  start_capital: string;
  end_capital: string;
  gross_return: string | null;
  net_return: string | null;
  max_drawdown: string | null;
  annualized_volatility: string | null;
  sharpe: string | null;
  sortino: string | null;
  exposure: string | null;
  turnover: string | null;
  trade_count: number;
  total_costs: string;
  sample_sessions: number;
  unavailable: string[];
};

export type ResearchEquityPoint = {
  strategy_id: string;
  session_date: string;
  equity: string;
  cash: string;
  exposure: string;
  drawdown: string;
  window: string;
};

export type ResearchSimulatedTrade = {
  id: number;
  strategy_id: string;
  session_date: string;
  symbol: string;
  side: string;
  quantity: string;
  price: string;
  notional: string;
  commission: string;
  spread_cost: string;
  slippage_cost: string;
  reason: string;
  is_simulated: true;
  is_broker_order: false;
};

export type ResearchSimulatedDecision = {
  id: number;
  run_id: number;
  strategy_id: string;
  session_date: string;
  decision_timestamp: string;
  data_cutoff: string;
  symbol: string;
  signal: string;
  feature_inputs: Record<string, unknown>;
  proposed_target_weight: string;
  action: string;
  rationale: string;
  evidence_hash: string;
  fill_session: string | null;
  fill_price: string | null;
  portfolio_before: Record<string, unknown>;
  portfolio_after: Record<string, unknown>;
  warnings: string[];
  is_simulated: true;
  is_broker_order: false;
  audit_decision_id: number | null;
};

export type ResearchReplay = {
  run_id: number;
  checked_decisions: number;
  mismatch_count: number;
  mismatches: Record<string, unknown>[];
  ok: boolean;
  verdict: string;
  label: string;
  is_broker_execution: false;
};

function readOptionalDecimalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  throw new Error(`Unexpected ${label}`);
}

function readDecimalString(value: unknown, label: string): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  throw new Error(`Unexpected ${label}`);
}

function parseResearchExperiment(value: unknown): ResearchExperiment {
  if (!isRecord(value)) {
    throw new Error("Unexpected experiment");
  }
  if (
    typeof value.experiment_id !== "string" ||
    typeof value.hypothesis_id !== "string" ||
    typeof value.title !== "string" ||
    typeof value.description !== "string" ||
    typeof value.created_at !== "string"
  ) {
    throw new Error("Unexpected experiment field");
  }
  return {
    experiment_id: value.experiment_id,
    hypothesis_id: value.hypothesis_id,
    title: value.title,
    description: value.description,
    citations: readStringList(value.citations, "citations"),
    created_at: value.created_at,
    config: readPayload(value.config),
  };
}

function parseResearchRun(value: unknown): ResearchRun {
  if (!isRecord(value) || typeof value.id !== "number") {
    throw new Error("Unexpected research run");
  }
  if (
    typeof value.experiment_id !== "string" ||
    typeof value.created_at !== "string" ||
    typeof value.status !== "string" ||
    typeof value.engine_version !== "string" ||
    typeof value.dataset_fingerprint !== "string" ||
    typeof value.outcome_summary !== "string" ||
    typeof value.label !== "string" ||
    typeof value.error_code !== "string" ||
    typeof value.error_message_safe !== "string"
  ) {
    throw new Error("Unexpected research run field");
  }
  if (value.is_paper_trading !== false || value.is_broker_execution !== false) {
    throw new Error("Research run is not marked as offline backtest");
  }
  return {
    id: value.id,
    experiment_id: value.experiment_id,
    created_at: value.created_at,
    finished_at: readOptionalString(value.finished_at, "finished at"),
    status: value.status,
    git_commit: readOptionalString(value.git_commit, "git commit"),
    engine_version: value.engine_version,
    dataset_fingerprint: value.dataset_fingerprint,
    outcome_summary: value.outcome_summary,
    caveats: readStringList(value.caveats, "caveats"),
    label: value.label,
    is_paper_trading: false,
    is_broker_execution: false,
    config: readPayload(value.config),
    audit_run_id: typeof value.audit_run_id === "number" ? value.audit_run_id : null,
    error_code: value.error_code,
    error_message_safe: value.error_message_safe,
  };
}

function parseResearchMetric(value: unknown): ResearchMetric {
  if (!isRecord(value)) {
    throw new Error("Unexpected research metric");
  }
  if (typeof value.strategy_id !== "string" || typeof value.window !== "string") {
    throw new Error("Unexpected metric identity");
  }
  if (typeof value.trade_count !== "number" || typeof value.sample_sessions !== "number") {
    throw new Error("Unexpected metric counts");
  }
  return {
    strategy_id: value.strategy_id,
    window: value.window,
    start_capital: readDecimalString(value.start_capital, "start capital"),
    end_capital: readDecimalString(value.end_capital, "end capital"),
    gross_return: readOptionalDecimalString(value.gross_return, "gross return"),
    net_return: readOptionalDecimalString(value.net_return, "net return"),
    max_drawdown: readOptionalDecimalString(value.max_drawdown, "max drawdown"),
    annualized_volatility: readOptionalDecimalString(value.annualized_volatility, "volatility"),
    sharpe: readOptionalDecimalString(value.sharpe, "sharpe"),
    sortino: readOptionalDecimalString(value.sortino, "sortino"),
    exposure: readOptionalDecimalString(value.exposure, "exposure"),
    turnover: readOptionalDecimalString(value.turnover, "turnover"),
    trade_count: value.trade_count,
    total_costs: readDecimalString(value.total_costs, "total costs"),
    sample_sessions: value.sample_sessions,
    unavailable: readStringList(value.unavailable, "unavailable"),
  };
}

function parseResearchEquityPoint(value: unknown): ResearchEquityPoint {
  if (!isRecord(value)) {
    throw new Error("Unexpected equity point");
  }
  const fields = ["strategy_id", "session_date", "equity", "cash", "exposure", "drawdown", "window"] as const;
  const point = {} as ResearchEquityPoint;
  for (const field of fields) {
    if (typeof value[field] !== "string") {
      throw new Error("Unexpected equity field");
    }
    point[field] = value[field];
  }
  return point;
}

function parseResearchTrade(value: unknown): ResearchSimulatedTrade {
  if (!isRecord(value) || typeof value.id !== "number") {
    throw new Error("Unexpected simulated trade");
  }
  const fields = [
    "strategy_id",
    "session_date",
    "symbol",
    "side",
    "quantity",
    "price",
    "notional",
    "commission",
    "spread_cost",
    "slippage_cost",
    "reason",
  ] as const;
  const trade = { id: value.id } as ResearchSimulatedTrade;
  for (const field of fields) {
    if (typeof value[field] !== "string") {
      throw new Error("Unexpected trade field");
    }
    trade[field] = value[field];
  }
  if (value.is_simulated !== true || value.is_broker_order !== false) {
    throw new Error("Trade is not marked simulated");
  }
  trade.is_simulated = true;
  trade.is_broker_order = false;
  return trade;
}

function parseResearchDecision(value: unknown): ResearchSimulatedDecision {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.run_id !== "number") {
    throw new Error("Unexpected simulated decision");
  }
  const strings = [
    "strategy_id",
    "session_date",
    "decision_timestamp",
    "data_cutoff",
    "symbol",
    "signal",
    "proposed_target_weight",
    "action",
    "rationale",
    "evidence_hash",
  ] as const;
  const decision = {
    id: value.id,
    run_id: value.run_id,
  } as ResearchSimulatedDecision;
  for (const field of strings) {
    if (typeof value[field] !== "string") {
      throw new Error("Unexpected decision field");
    }
    decision[field] = value[field];
  }
  if (value.is_simulated !== true || value.is_broker_order !== false) {
    throw new Error("Decision is not marked simulated");
  }
  return {
    ...decision,
    feature_inputs: readPayload(value.feature_inputs),
    fill_session: readOptionalString(value.fill_session, "fill session"),
    fill_price: readOptionalString(value.fill_price, "fill price"),
    portfolio_before: readPayload(value.portfolio_before),
    portfolio_after: readPayload(value.portfolio_after),
    warnings: readStringList(value.warnings, "warnings"),
    is_simulated: true,
    is_broker_order: false,
    audit_decision_id: typeof value.audit_decision_id === "number" ? value.audit_decision_id : null,
  };
}

export function parseResearchExperimentPage(value: unknown): { items: ResearchExperiment[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected experiment page");
  }
  return { items: value.items.map(parseResearchExperiment), total: value.total };
}

export function parseResearchExperimentDetail(value: unknown): ResearchExperiment & { runs: ResearchRun[] } {
  if (!isRecord(value) || !Array.isArray(value.runs)) {
    throw new Error("Unexpected experiment detail");
  }
  const experiment = parseResearchExperiment(value);
  return { ...experiment, runs: value.runs.map(parseResearchRun) };
}

export function parseResearchRunPage(value: unknown): { items: ResearchRun[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected research run page");
  }
  return { items: value.items.map(parseResearchRun), total: value.total };
}

export function parseResearchRunDetail(value: unknown): ResearchRunDetail {
  if (!isRecord(value) || !Array.isArray(value.metrics)) {
    throw new Error("Unexpected research run detail");
  }
  const run = parseResearchRun(value);
  if (typeof value.research_mode !== "string") {
    throw new Error("Unexpected research mode");
  }
  return {
    ...run,
    metrics: value.metrics.map(parseResearchMetric),
    research_mode: value.research_mode,
  };
}

export function parseResearchEquityPage(value: unknown): { items: ResearchEquityPoint[]; total: number } {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected equity page");
  }
  return { items: value.items.map(parseResearchEquityPoint), total: value.total };
}

export function parseResearchTradesPage(value: unknown): {
  items: ResearchSimulatedTrade[];
  total: number;
  note: string;
} {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected trades page");
  }
  if (typeof value.note !== "string") {
    throw new Error("Unexpected trades note");
  }
  return { items: value.items.map(parseResearchTrade), total: value.total, note: value.note };
}

export function parseResearchDecisionsPage(value: unknown): {
  items: ResearchSimulatedDecision[];
  total: number;
  note: string;
} {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected decisions page");
  }
  if (typeof value.note !== "string") {
    throw new Error("Unexpected decisions note");
  }
  return { items: value.items.map(parseResearchDecision), total: value.total, note: value.note };
}

export function parseResearchDecisionDetail(value: unknown): ResearchSimulatedDecision {
  return parseResearchDecision(value);
}

export function parseResearchReplay(value: unknown): ResearchReplay {
  if (!isRecord(value)) {
    throw new Error("Unexpected replay payload");
  }
  if (
    typeof value.run_id !== "number" ||
    typeof value.checked_decisions !== "number" ||
    typeof value.mismatch_count !== "number" ||
    typeof value.ok !== "boolean" ||
    typeof value.verdict !== "string" ||
    typeof value.label !== "string" ||
    !Array.isArray(value.mismatches)
  ) {
    throw new Error("Unexpected replay field");
  }
  if (value.is_broker_execution !== false) {
    throw new Error("Replay is not marked offline");
  }
  return {
    run_id: value.run_id,
    checked_decisions: value.checked_decisions,
    mismatch_count: value.mismatch_count,
    mismatches: value.mismatches.map((item) => readPayload(item)),
    ok: value.ok,
    verdict: value.verdict,
    label: value.label,
    is_broker_execution: false,
  };
}

export async function loadResearchExperiments(): Promise<{ items: ResearchExperiment[]; total: number }> {
  return parseResearchExperimentPage(await readJson("/api/research/experiments"));
}

export async function loadResearchExperiment(
  experimentId: string,
): Promise<ResearchExperiment & { runs: ResearchRun[] }> {
  return parseResearchExperimentDetail(await readJson(`/api/research/experiments/${encodeURIComponent(experimentId)}`));
}

export async function loadResearchRuns(experimentId?: string): Promise<{ items: ResearchRun[]; total: number }> {
  const query = experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : "";
  return parseResearchRunPage(await readJson(`/api/research/runs${query}`));
}

export async function loadResearchRun(id: number): Promise<ResearchRunDetail> {
  return parseResearchRunDetail(await readJson(`/api/research/runs/${id}`));
}

export async function loadResearchRunEquity(id: number): Promise<{ items: ResearchEquityPoint[]; total: number }> {
  return parseResearchEquityPage(await readJson(`/api/research/runs/${id}/equity`));
}

export async function loadResearchRunTrades(id: number): Promise<{
  items: ResearchSimulatedTrade[];
  total: number;
  note: string;
}> {
  return parseResearchTradesPage(await readJson(`/api/research/runs/${id}/trades`));
}

export async function loadResearchRunDecisions(
  id: number,
  opts?: { limit?: number; offset?: number; strategyId?: string; action?: string },
): Promise<{
  items: ResearchSimulatedDecision[];
  total: number;
  note: string;
  limit?: number;
  offset?: number;
}> {
  const query = new URLSearchParams();
  if (opts?.limit !== undefined) {
    query.set("limit", String(opts.limit));
  }
  if (opts?.offset !== undefined) {
    query.set("offset", String(opts.offset));
  }
  if (opts?.strategyId) {
    query.set("strategy_id", opts.strategyId);
  }
  if (opts?.action) {
    query.set("action", opts.action);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return parseResearchDecisionsPage(await readJson(`/api/research/runs/${id}/decisions${suffix}`));
}

export async function loadResearchDecision(id: number): Promise<ResearchSimulatedDecision> {
  return parseResearchDecisionDetail(await readJson(`/api/research/decisions/${id}`));
}

export async function loadResearchRunReplay(id: number): Promise<ResearchReplay> {
  return parseResearchReplay(await readJson(`/api/research/runs/${id}/replay`));
}

export function formatReturn(value: string | null): string {
  if (value === null) {
    return "n/a";
  }
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return value;
  }
  return `${(amount * 100).toFixed(2)}%`;
}

export function configString(config: Record<string, unknown>, key: string): string | null {
  const raw = config[key];
  if (raw === null || raw === undefined) {
    return null;
  }
  if (typeof raw === "string") {
    return raw;
  }
  if (typeof raw === "number" || typeof raw === "boolean") {
    return String(raw);
  }
  return null;
}

export type AgentModelDetail = {
  name: string;
  digest?: string;
  size?: number | null;
  modified_at?: string;
  family?: string;
  parameter_size?: string;
};

export type AgentStatus = {
  ollama: {
    available: boolean;
    base_url: string;
    models: string[];
    latency_ms?: number;
    error?: string;
  };
  configured_model: string;
  installed_models?: AgentModelDetail[];
  prompt_version: string;
  tool_schema_version: string;
  benchmark_version?: string;
  label: string;
  tools: string[];
  order_tools_available: false;
  trading_mode: "paper";
  run_count: number;
};

export type AgentBenchmarkRow = {
  id: number;
  created_at: string;
  model: string;
  model_digest: string;
  research_run_id: number;
  context_tokens: number | null;
  trial_index: number;
  metrics: Record<string, unknown>;
  benchmark_version: string;
};

export type AgentRunSummary = {
  id: number;
  created_at: string;
  finished_at: string | null;
  status: string;
  research_run_id: number;
  model: string;
  verdict: string;
  summary: string;
  label: string;
  error_message_safe?: string;
};

export type AgentRunDetail = AgentRunSummary & {
  stages: Array<Record<string, unknown>>;
  tool_calls: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  fingerprint?: string;
  prompt_version?: string;
  tool_schema_version?: string;
  as_of?: string;
  result?: Record<string, unknown>;
  config?: Record<string, unknown>;
};

export async function loadAgentStatus(): Promise<AgentStatus> {
  const value = await readJson("/api/agents/status");
  if (
    !isRecord(value) ||
    !isRecord(value.ollama) ||
    typeof value.ollama.available !== "boolean" ||
    !Array.isArray(value.ollama.models)
  ) {
    throw new Error("Unexpected agent status");
  }
  if (value.order_tools_available !== false || value.trading_mode !== "paper") {
    throw new Error("Agent status violates paper-only locks");
  }
  return value as AgentStatus;
}

export async function loadAgentRuns(
  query = "?limit=50",
): Promise<{ items: AgentRunSummary[]; total: number }> {
  const value = await readJson(`/api/agents/runs${query}`);
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected agent runs page");
  }
  return {
    total: value.total,
    items: value.items.map((item) => {
      if (!isRecord(item) || typeof item.id !== "number") {
        throw new Error("Unexpected agent run");
      }
      return item as AgentRunSummary;
    }),
  };
}

export async function loadAgentRun(id: number): Promise<AgentRunDetail> {
  const value = await readJson(`/api/agents/runs/${id}`);
  if (!isRecord(value) || typeof value.id !== "number") {
    throw new Error("Unexpected agent run detail");
  }
  return value as AgentRunDetail;
}

export async function loadAgentBenchmarks(
  limit = 50,
): Promise<{ items: AgentBenchmarkRow[]; benchmark_version: string }> {
  const value = await readJson(`/api/agents/benchmarks?limit=${limit}`);
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new Error("Unexpected agent benchmarks");
  }
  return {
    benchmark_version: String(value.benchmark_version ?? ""),
    items: value.items.filter(isRecord).map((item) => item as AgentBenchmarkRow),
  };
}

export type RiskStatus = {
  label: string;
  is_broker_execution: false;
  order_submission_enabled: false;
  allow_order_submission: false;
  trading_mode: "paper";
  internal_capital_usd: number;
  policy_version: string;
  policy_hash: string;
  policy: Record<string, unknown>;
  evaluation_count: number;
  note: string;
};

export type RiskEvaluation = {
  id: number;
  proposal_id: string;
  created_at: string;
  source: string;
  symbol: string;
  side: string;
  quantity: string;
  verdict: string;
  reasons: string[];
  rule_verdicts: Array<Record<string, unknown>>;
  policy_version: string;
  policy_hash: string;
  notional_usd: string | null;
  projected_cash_usd: string | null;
  agent_run_id: number | null;
};

export async function loadRiskStatus(): Promise<RiskStatus> {
  const value = await readJson("/api/risk/status");
  if (
    !isRecord(value) ||
    value.is_broker_execution !== false ||
    value.order_submission_enabled !== false ||
    value.allow_order_submission !== false
  ) {
    throw new Error("Risk status violates paper-only locks");
  }
  return value as RiskStatus;
}

export async function loadRiskEvaluations(
  query = "?limit=50",
): Promise<{ items: RiskEvaluation[]; total: number }> {
  const value = await readJson(`/api/risk/evaluations${query}`);
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected risk evaluations");
  }
  return {
    total: value.total,
    items: value.items.filter(isRecord).map((item) => item as RiskEvaluation),
  };
}

export type ShadowPositionValue = {
  symbol: string;
  quantity: string;
  mark_price: string;
  market_value_usd: string;
  cost_basis_usd: string;
  unrealized_pnl_usd: string;
  mark_as_of: string;
  feed: string;
};

export type ShadowValuation = {
  status: "ok" | "stale" | "valuation_unavailable";
  cash_usd: string;
  reserved_cash_usd: string;
  available_cash_usd: string;
  positions: ShadowPositionValue[];
  equity_usd: string | null;
  exposure_usd: string | null;
  exposure_fraction: string | null;
  realized_pnl_usd: string;
  unrealized_pnl_usd: string | null;
  total_costs_usd: string;
  starting_capital_usd: string;
  valuation_as_of: string | null;
  reason: string;
  ledger_version: number;
  note?: string;
};

export type ShadowStatus = {
  trading_state: string;
  allow_order_submission: false | boolean;
  initialized: boolean;
  starting_capital_usd: string;
  cash_usd?: string;
  reserved_cash_usd?: string;
  holdings?: Record<string, string>;
  cost_basis?: Record<string, string>;
  realized_pnl_usd?: string;
  total_costs_usd?: string;
  peak_equity_usd?: string;
  ledger_version?: number;
  updated_at?: string;
  cycle_count: number;
  valuation?: ShadowValuation | null;
  valuation_reason?: string | null;
  note: string;
};

export type ShadowOpsAlert = {
  level: string;
  source: string;
  message: string;
  cycle_id?: number;
};

export type ShadowWorkerRunSummary = {
  run_id?: string;
  worker_status?: string;
  mode?: string;
  started_at?: string;
  finished_at?: string;
};

export type ShadowOps = {
  market: {
    database_present: boolean;
    feed: string | null;
    symbols: string[];
    feeds: string[];
    earliest_session: string | null;
    latest_session: string | null;
    bar_count: number;
    coverage_complete: boolean;
    suitable_for_research: boolean;
    last_successful_ingestion: string | null;
    requested_start: string | null;
    requested_end: string | null;
    warnings: string[];
    coverage: Array<Record<string, unknown>>;
    caveat: string;
  };
  pending_intents: Array<Record<string, unknown>>;
  pending_intent_count?: number;
  recovery_required?: boolean;
  outbox_backlog?: number | null;
  last_worker_run?: ShadowWorkerRunSummary | null;
  worker_runs?: {
    items: ShadowWorkerRunSummary[];
    total: number;
    corrupt: string[];
  };
  data_health?: {
    status?: string;
    feed?: string;
    eligible_end?: string | null;
    symbols?: Record<
      string,
      {
        latest_stored?: string | null;
        missing_count?: number;
        warmup_complete?: boolean;
      }
    >;
  } | null;
  alerts: ShadowOpsAlert[];
  last_cycle: ShadowCycle | null;
  cycle_count: number;
};

export type ShadowTimelineItem = {
  id: number;
  cycle_key: string;
  created_at: string;
  mode: string;
  label: string;
  signal_session: string | null;
  fill_session: string | null;
  feed: string;
  symbol: string;
  status: string;
  intent: string;
  risk_verdict: string | null;
  evidence_hash: string;
  warnings: string[];
  transitions: Array<{ step: string; at: string }>;
};

export type ShadowCycle = {
  id: number;
  cycle_key: string;
  created_at: string;
  mode: string;
  label: string;
  signal_session: string | null;
  fill_session: string | null;
  status: string;
  intent: string;
  risk_verdict: string | null;
  evidence_hash: string;
  warnings: string[];
  evidence: Record<string, unknown>;
};

export async function loadShadowStatus(): Promise<ShadowStatus> {
  const value = await readJson("/api/shadow/status");
  if (!isRecord(value) || value.trading_state !== "SHADOW_ONLY") {
    throw new Error("Unexpected shadow status");
  }
  return value as ShadowStatus;
}

export async function loadShadowCycle(id: number): Promise<ShadowCycle & Record<string, unknown>> {
  const value = await readJson(`/api/shadow/cycles/${id}`);
  if (!isRecord(value) || typeof value.id !== "number") {
    throw new Error("Unexpected shadow cycle detail");
  }
  return value as ShadowCycle & Record<string, unknown>;
}

export async function loadShadowCycles(
  query = "?limit=50",
): Promise<{ items: ShadowCycle[]; total: number }> {
  const value = await readJson(`/api/shadow/cycles${query}`);
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    throw new Error("Unexpected shadow cycles");
  }
  return {
    total: value.total,
    items: value.items.filter(isRecord).map((item) => item as ShadowCycle),
  };
}

export async function loadShadowEquity(
  limit = 500,
): Promise<{ items: Array<Record<string, string | number | null>> }> {
  const value = await readJson(`/api/shadow/equity?limit=${limit}`);
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new Error("Unexpected shadow equity");
  }
  return { items: value.items as Array<Record<string, string | number | null>> };
}

function isShadowValuation(value: unknown): value is ShadowValuation {
  return (
    isRecord(value) &&
    typeof value.status === "string" &&
    typeof value.cash_usd === "string" &&
    Array.isArray(value.positions)
  );
}

export async function loadShadowValuation(): Promise<ShadowValuation> {
  const value = await readJson("/api/shadow/valuation");
  if (!isShadowValuation(value)) {
    throw new Error("Unexpected shadow valuation");
  }
  return value;
}

export async function loadShadowOps(): Promise<ShadowOps> {
  const value = await readJson("/api/shadow/ops");
  if (!isRecord(value) || !isRecord(value.market) || !Array.isArray(value.alerts)) {
    throw new Error("Unexpected shadow ops");
  }
  return value as ShadowOps;
}

export async function loadShadowTimeline(
  query = "?limit=50&offset=0",
): Promise<{ items: ShadowTimelineItem[]; total: number; limit: number; offset: number }> {
  const value = await readJson(`/api/shadow/timeline${query}`);
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number" ||
    typeof value.limit !== "number" ||
    typeof value.offset !== "number"
  ) {
    throw new Error("Unexpected shadow timeline");
  }
  return {
    total: value.total,
    limit: value.limit,
    offset: value.offset,
    items: value.items.filter(isRecord).map((item) => item as ShadowTimelineItem),
  };
}
