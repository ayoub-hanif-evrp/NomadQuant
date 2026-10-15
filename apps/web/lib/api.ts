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
